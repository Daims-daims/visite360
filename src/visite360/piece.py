"""Étape 10 : dimensions d'une pièce à partir des coins pointés dans son panorama (D13, D34).

Le panorama est pris d'un seul endroit, l'objectif à une hauteur connue au-dessus du sol :
l'app la mesure avec ARKit pendant la prise de vue « ×1 + AR » (`hauteur_objectif_m` de
`capture.json`). L'horizon du panorama est horizontal, puisque les capteurs du téléphone
donnent la verticale. Un coin au sol vu à `a` degrés sous l'horizon est alors à la distance
horizontale `hauteur de l'objectif / tan(a)`. Le même coin vu au plafond à `b` degrés au-dessus
donne la hauteur du plafond au-dessus de l'objectif : `distance × tan(b)`.

L'agent clique les coins dans l'ordre, en faisant le tour de la pièce, au sol si le coin est
visible, au plafond si un meuble le cache, et au moins un coin aux deux pour connaître la
hauteur sous plafond. Sans hauteur mesurée par l'app, il saisit la hauteur sous plafond : les
coins cliqués aux deux donnent alors la hauteur de l'objectif.

La pièce est enregistrée dans `<point>/piece.json` (format dans `docs/dimensions.md`). Les
dimensions sont recalculées à chaque lecture à partir des clics. Le panorama avec le contour
dessiné est fabriqué à la demande dans `cache/`. Le panorama d'origine n'est jamais modifié (D9).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from visite360 import capture, selection
from visite360.opencv import load_cv2
from visite360.spherical import directions_to_equirect

FILE_NAME = "piece.json"
FORMAT_VERSION = 1
CONTOUR_NAME = "piece.jpg"
CONTOUR_STATE = "piece-etat.json"
MAX_CLICKS = 60
# Un clic plus près de l'horizon ne donne pas de distance fiable : à 3°, une erreur d'un
# dixième de degré change déjà la distance de plus de 3 %.
MIN_ELEVATION_DEG = 3.0
# Un clic au plafond complète le coin précédent s'il est à moins de ce cap de son clic au sol
# (ou l'inverse). Dans le panorama, une arête verticale est une ligne de cap constant : le haut
# et le bas d'un même coin ont le même cap, à l'erreur de clic près.
SAME_CORNER_DEG = 4.0
MIN_LENS_HEIGHT_M, MAX_LENS_HEIGHT_M = 0.3, 2.5
MIN_CEILING_M, MAX_CEILING_M = 1.8, 6.0
JPEG_QUALITY = 90
FLOOR_BGR = (0, 220, 255)
CEILING_BGR = (255, 160, 60)
EDGE_BGR = (255, 255, 255)
CLICK_BGR = {"sol": (0, 220, 255), "plafond": (255, 160, 60)}


class PieceError(Exception):
    """Mesure impossible ou fiche mal formée, avec un message en français."""


@dataclass(frozen=True)
class Click:
    """Clic dans le panorama : cap (positif vers la droite) et hauteur (positive vers le haut)."""

    yaw: float
    pitch: float

    @property
    def level(self) -> str:
        return "plafond" if self.pitch > 0 else "sol"

    def to_json(self) -> dict[str, float]:
        return {"cap": round(self.yaw, 2), "hauteur": round(self.pitch, 2)}


@dataclass(frozen=True)
class Corner:
    """Un coin de la pièce : son clic au sol, au plafond, ou les deux."""

    floor: Click | None
    ceiling: Click | None

    @property
    def yaw(self) -> float:
        return (self.floor or self.ceiling).yaw  # type: ignore[union-attr]


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def parse_clicks(raw: Any) -> list[Click]:
    """Lit les clics envoyés par la visionneuse : [{"cap", "hauteur"}, ...]."""
    if not isinstance(raw, list):
        raise PieceError("Clics illisibles : une liste est attendue.")
    if len(raw) > MAX_CLICKS:
        raise PieceError(f"Trop de clics ({len(raw)}, au plus {MAX_CLICKS}).")
    clicks = []
    for number, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict) or not all(
            _number(entry.get(key)) for key in ("cap", "hauteur")
        ):
            raise PieceError(f"Clic {number} illisible : cap et hauteur doivent être des nombres.")
        yaw, pitch = float(entry["cap"]), float(entry["hauteur"])
        if not -90.0 <= pitch <= 90.0:
            raise PieceError(f"Clic {number} : hauteur hors limites ({pitch}°).")
        if abs(pitch) < MIN_ELEVATION_DEG:
            raise PieceError(
                f"Clic {number} trop près de l'horizon : cliquer le coin au ras du sol ou du "
                "plafond, pas à mi-hauteur du mur."
            )
        clicks.append(Click((yaw + 180.0) % 360.0 - 180.0, pitch))
    return clicks


def _yaw_gap(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def group_corners(clicks: list[Click]) -> list[Corner]:
    """Regroupe les clics en coins, dans l'ordre où ils ont été faits.

    Un clic complète le coin précédent s'il est de l'autre niveau (sol ou plafond), que ce
    niveau manque encore à ce coin, et qu'il est presque dans la même direction. Sinon il ouvre
    un nouveau coin.
    """
    corners: list[Corner] = []
    for click in clicks:
        if corners:
            last = corners[-1]
            other = last.ceiling if click.level == "sol" else last.floor
            missing = last.floor if click.level == "sol" else last.ceiling
            if (
                missing is None
                and other is not None
                and _yaw_gap(other.yaw, click.yaw) <= SAME_CORNER_DEG
            ):
                if click.level == "sol":
                    corners[-1] = Corner(click, last.ceiling)
                else:
                    corners[-1] = Corner(last.floor, click)
                continue
        corners.append(Corner(click, None) if click.level == "sol" else Corner(None, click))
    return corners


def _tan(click: Click) -> float:
    return math.tan(math.radians(abs(click.pitch)))


def _segments_cross(p1: np.ndarray, p2: np.ndarray, q1: np.ndarray, q2: np.ndarray) -> bool:
    def side(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
        return float((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))

    d1, d2 = side(q1, q2, p1), side(q1, q2, p2)
    d3, d4 = side(p1, p2, q1), side(p1, p2, q2)
    return d1 * d2 < 0 and d3 * d4 < 0


@dataclass(frozen=True)
class Room:
    """Pièce calculée. Plan vu de dessus en mètres, objectif à l'origine : x vers la droite du
    centre du panorama, z vers son centre."""

    corners: list[Corner]
    plan: np.ndarray
    lens_height: float
    ceiling_height: float
    lens_source: str
    ceiling_source: str
    # Écart entre les hauteurs sous plafond données par chaque coin cliqué aux deux, en mètres :
    # grand, il signale un clic à côté d'un coin ou un horizon penché.
    spread: float | None

    @property
    def walls(self) -> list[tuple[float, float]]:
        """(longueur, surface) de chaque mur, du coin n au coin n + 1."""
        result = []
        for index in range(len(self.plan)):
            a, b = self.plan[index], self.plan[(index + 1) % len(self.plan)]
            length = float(np.hypot(*(b - a)))
            result.append((length, length * self.ceiling_height))
        return result

    @property
    def floor_area(self) -> float:
        x, z = self.plan[:, 0], self.plan[:, 1]
        return float(abs(np.dot(x, np.roll(z, -1)) - np.dot(z, np.roll(x, -1))) / 2.0)

    @property
    def perimeter(self) -> float:
        return sum(length for length, _ in self.walls)

    def to_json(self) -> dict[str, Any]:
        def r(value: float, digits: int = 2) -> float:
            return round(value, digits)

        return {
            "hauteur_objectif_m": r(self.lens_height, 3),
            "source_hauteur_objectif": self.lens_source,
            "hauteur_plafond_m": r(self.ceiling_height),
            "source_hauteur_plafond": self.ceiling_source,
            "ecart_hauteur_plafond_m": None if self.spread is None else r(self.spread),
            "murs": [
                {"numero": n, "longueur_m": r(length), "surface_m2": r(area, 1)}
                for n, (length, area) in enumerate(self.walls, start=1)
            ],
            "surface_sol_m2": r(self.floor_area, 1),
            "perimetre_m": r(self.perimeter),
            "plan_m": [[r(x), r(z)] for x, z in self.plan],
        }


def compute(clicks: list[Click], lens_height: float | None, ceiling_height: float | None) -> Room:
    """Calcule la pièce à partir des clics et d'une hauteur connue.

    `lens_height` est la hauteur de l'objectif mesurée par l'app ; `ceiling_height` la hauteur
    sous plafond saisie, utilisée quand l'app n'a pas mesuré l'objectif ou qu'aucun coin n'est
    cliqué aux deux.
    """
    if lens_height is not None and not MIN_LENS_HEIGHT_M <= lens_height <= MAX_LENS_HEIGHT_M:
        raise PieceError(f"Hauteur de l'objectif invraisemblable : {lens_height:.2f} m.")
    if ceiling_height is not None and not MIN_CEILING_M <= ceiling_height <= MAX_CEILING_M:
        raise PieceError(
            f"Hauteur sous plafond hors limites : {ceiling_height:.2f} m "
            f"(de {MIN_CEILING_M:g} à {MAX_CEILING_M:g} m)."
        )
    corners = group_corners(clicks)
    if len(corners) < 3:
        raise PieceError(f"{len(corners)} coin(s) pointé(s) : il en faut au moins 3.")
    pairs = [c for c in corners if c.floor is not None and c.ceiling is not None]

    if lens_height is not None:
        lens, lens_source = lens_height, "app"
        # Hauteur du plafond au-dessus de l'objectif, par chaque coin cliqué aux deux.
        above = [lens / _tan(c.floor) * _tan(c.ceiling) for c in pairs]  # type: ignore[arg-type]
        if above:
            ceiling, ceiling_source = lens + float(np.mean(above)), "coins"
            spread: float | None = float(np.ptp(above)) if len(above) > 1 else None
        elif ceiling_height is not None:
            ceiling, ceiling_source, spread = ceiling_height, "saisie", None
        else:
            raise PieceError(
                "Hauteur sous plafond inconnue : cliquer au moins un coin au sol puis au plafond, "
                "ou la saisir."
            )
    else:
        if ceiling_height is None:
            raise PieceError(
                "L'app n'a pas mesuré la hauteur de l'objectif pour ce point : saisir la hauteur "
                "sous plafond."
            )
        if not pairs:
            raise PieceError(
                "Sans hauteur mesurée par l'app, cliquer au moins un coin au sol puis au plafond."
            )
        # Coin vu à a sous l'horizon et à b au-dessus :
        # objectif = plafond × tan a / (tan a + tan b).
        lenses = [
            ceiling_height * _tan(c.floor) / (_tan(c.floor) + _tan(c.ceiling))  # type: ignore[arg-type]
            for c in pairs
        ]
        lens, lens_source = float(np.mean(lenses)), "plafond_saisi"
        ceiling, ceiling_source = ceiling_height, "saisie"
        spread = None
        if len(lenses) > 1:
            above = [lens / _tan(c.floor) * _tan(c.ceiling) for c in pairs]  # type: ignore[arg-type]
            spread = float(np.ptp(above))
    if not MIN_CEILING_M <= ceiling <= MAX_CEILING_M:
        raise PieceError(
            f"Hauteur sous plafond calculée invraisemblable : {ceiling:.2f} m. Un clic au plafond "
            "est peut-être à côté de son coin."
        )
    if ceiling <= lens:
        raise PieceError("Plafond calculé sous l'objectif : vérifier les clics au plafond.")

    plan = []
    for corner in corners:
        if corner.floor is not None:
            distance = lens / _tan(corner.floor)
        else:
            distance = (ceiling - lens) / _tan(corner.ceiling)  # type: ignore[arg-type]
        yaw = math.radians(corner.yaw)
        plan.append((distance * math.sin(yaw), distance * math.cos(yaw)))
    points = np.array(plan)
    count = len(points)
    for i in range(count):
        for j in range(i + 1, count):
            if j == i + 1 or (i == 0 and j == count - 1):
                continue
            if _segments_cross(
                points[i], points[(i + 1) % count], points[j], points[(j + 1) % count]
            ):
                raise PieceError(
                    f"Les murs {i + 1} et {j + 1} se croisent : les coins doivent être cliqués "
                    "dans l'ordre, en faisant le tour de la pièce."
                )
    return Room(corners, points, lens, ceiling, lens_source, ceiling_source, spread)


def lens_height(point: Path) -> float | None:
    """Hauteur de l'objectif mesurée par l'app pour ce point, ou None."""
    path = capture.find(point)
    if path is None:
        return None
    try:
        return capture.load(path).lens_height
    except capture.CaptureError:
        return None


def parse_ceiling(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    if not _number(raw):
        raise PieceError("Hauteur sous plafond illisible : un nombre de mètres est attendu.")
    return float(raw)


def measure(point: Path, raw_clicks: Any, raw_ceiling: Any) -> Room:
    """Calcule la pièce d'un point à partir de ce qu'envoie la visionneuse."""
    return compute(parse_clicks(raw_clicks), lens_height(point), parse_ceiling(raw_ceiling))


def _record(point: Path) -> dict[str, Any] | None:
    path = point / FILE_NAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PieceError(f"{FILE_NAME} illisible ({error}).") from error
    if not isinstance(data, dict) or data.get("version") != FORMAT_VERSION:
        raise PieceError(f"{FILE_NAME} : format inconnu.")
    return data


def load(point: Path, panorama: Path) -> dict[str, Any] | None:
    """Pièce enregistrée, dimensions recalculées, ou None. `perimee` : le panorama a été refait
    depuis, les clics ne tombent peut-être plus sur les coins."""
    record = _record(point)
    if record is None:
        return None
    room = _recompute(record)
    current = selection.file_sha256(panorama) if panorama.is_file() else None
    stale = record.get("panorama_sha256") != current
    return {**record, "resultat": room.to_json(), "perimee": stale}


def load_room(point: Path, panorama: Path) -> tuple[Room | None, bool]:
    """Pièce enregistrée du point et « périmée » (voir `load`), ou (None, False) sans mesure."""
    record = load(point, panorama)
    if record is None:
        return None, False
    return _recompute(record), bool(record["perimee"])


def _recompute(record: dict[str, Any]) -> Room:
    """Pièce d'une fiche, avec les hauteurs connues au moment de l'enregistrement."""
    return compute(
        parse_clicks(record.get("clics")),
        record.get("hauteur_objectif_app_m"),
        record.get("hauteur_plafond_saisie_m"),
    )


def save(point: Path, panorama: Path, raw_clicks: Any, raw_ceiling: Any) -> dict[str, Any]:
    """Calcule et enregistre la pièce du point, en remplaçant l'éventuelle précédente."""
    clicks = parse_clicks(raw_clicks)
    lens, ceiling = lens_height(point), parse_ceiling(raw_ceiling)
    room = compute(clicks, lens, ceiling)
    record = {
        "version": FORMAT_VERSION,
        "type": "piece",
        "clics": [click.to_json() for click in clicks],
        "hauteur_objectif_app_m": lens,
        "hauteur_plafond_saisie_m": ceiling,
        "resultat": room.to_json(),
        "panorama_sha256": selection.file_sha256(panorama),
        "creee_le": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    data = json.dumps(record, ensure_ascii=False, indent=2).encode("utf-8")
    selection.write_atomic(point / FILE_NAME, data)
    return {**record, "perimee": False}


def delete(point: Path) -> None:
    (point / FILE_NAME).unlink(missing_ok=True)


def _polyline(points: np.ndarray, width: int, height: int) -> list[np.ndarray]:
    """Points du monde (objectif à l'origine, y vers le bas) en morceaux de ligne du panorama,
    coupés là où la ligne passe d'un bord de l'image à l'autre."""
    pixels = directions_to_equirect(points, width, height)
    pieces, start = [], 0
    for i in range(1, len(pixels)):
        if abs(pixels[i, 0] - pixels[i - 1, 0]) > width / 2:
            pieces.append(pixels[start:i])
            start = i
    pieces.append(pixels[start:])
    return [np.round(piece).astype(np.int32) for piece in pieces if len(piece) > 1]


def _segment(a: np.ndarray, b: np.ndarray, steps: int = 64) -> np.ndarray:
    t = np.linspace(0.0, 1.0, steps)[:, None]
    return a[None, :] * (1 - t) + b[None, :] * t


def draw(image: np.ndarray, clicks: list[Click], room: Room | None) -> np.ndarray:
    """Copie du panorama avec les clics et, si la pièce est calculée, ses arêtes et ses murs
    numérotés : sol en jaune, plafond en bleu, angles verticaux en blanc."""
    cv2 = load_cv2()
    out = image.copy()
    height, width = out.shape[:2]
    thickness = max(2, width // 1400)
    if room is not None:
        floor_y, ceiling_y = room.lens_height, room.lens_height - room.ceiling_height
        count = len(room.plan)
        for index in range(count):
            a, b = room.plan[index], room.plan[(index + 1) % count]
            for y, color in ((floor_y, FLOOR_BGR), (ceiling_y, CEILING_BGR)):
                line = _segment(np.array([a[0], y, a[1]]), np.array([b[0], y, b[1]]))
                for piece in _polyline(line, width, height):
                    cv2.polylines(out, [piece], False, color, thickness, cv2.LINE_AA)
            edge = _segment(np.array([a[0], floor_y, a[1]]), np.array([a[0], ceiling_y, a[1]]))
            for piece in _polyline(edge, width, height):
                cv2.polylines(out, [piece], False, EDGE_BGR, thickness, cv2.LINE_AA)
            middle = (a + b) / 2.0
            centre = np.array([[middle[0], (floor_y + ceiling_y) / 2.0, middle[1]]])
            col, row = directions_to_equirect(centre, width, height)[0]
            text, scale = str(index + 1), width / 2400
            (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness * 2)
            origin = (int(col - w / 2), int(row + h / 2))
            cv2.putText(
                out,
                text,
                origin,
                cv2.FONT_HERSHEY_SIMPLEX,
                scale,
                (0, 0, 0),
                thickness * 5,
                cv2.LINE_AA,
            )
            cv2.putText(
                out,
                text,
                origin,
                cv2.FONT_HERSHEY_SIMPLEX,
                scale,
                (255, 255, 255),
                thickness * 2,
                cv2.LINE_AA,
            )
    radius = max(6, width // 700)
    for click in clicks:
        col = (click.yaw + 180.0) / 360.0 * width - 0.5
        row = (90.0 - click.pitch) / 180.0 * height - 0.5
        centre = (int(round(col)), int(round(row)))
        cv2.circle(out, centre, radius + thickness, (0, 0, 0), -1, cv2.LINE_AA)
        cv2.circle(out, centre, radius, CLICK_BGR[click.level], -1, cv2.LINE_AA)
    return out


def _encode(image: np.ndarray) -> bytes:
    cv2 = load_cv2()
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        raise PieceError("L'écriture du panorama avec le contour a échoué.")
    return encoded.tobytes()


def _read_small(panorama: Path, width: int) -> np.ndarray:
    cv2 = load_cv2()
    image = cv2.imread(str(panorama))
    if image is None:
        raise PieceError(f"Panorama illisible : {panorama}")
    if image.shape[1] > width:
        image = cv2.resize(image, (width, width // 2), interpolation=cv2.INTER_AREA)
    return image


def preview(panorama: Path, point: Path, raw_clicks: Any, raw_ceiling: Any, width: int) -> bytes:
    """Panorama réduit avec les clics en cours et, dès qu'elle se calcule, la pièce."""
    clicks = parse_clicks(raw_clicks)
    try:
        room: Room | None = compute(clicks, lens_height(point), parse_ceiling(raw_ceiling))
    except PieceError:
        room = None
    return _encode(draw(_read_small(panorama, width), clicks, room))


def contour(point: Path, panorama: Path, width: int) -> Path:
    """Panorama réduit avec le contour de la pièce enregistrée, refait s'il est périmé."""
    record = _record(point)
    if record is None:
        raise PieceError("Ce point n'a pas encore de pièce mesurée.")
    signature = hashlib.sha256(
        (point / FILE_NAME).read_bytes() + str(panorama.stat().st_mtime_ns).encode()
    ).hexdigest()
    cache = point / "cache"
    target, state = cache / CONTOUR_NAME, cache / CONTOUR_STATE
    try:
        saved = json.loads(state.read_text(encoding="utf-8")) if state.is_file() else None
    except (OSError, ValueError):
        saved = None
    if not (isinstance(saved, dict) and saved.get("signature") == signature and target.is_file()):
        clicks = parse_clicks(record.get("clics"))
        image = draw(_read_small(panorama, width), clicks, _recompute(record))
        cache.mkdir(exist_ok=True)
        selection.write_atomic(target, _encode(image))
        selection.write_atomic(state, json.dumps({"signature": signature}).encode())
    return target
