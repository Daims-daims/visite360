"""Étape 14 : le programme qui tourne sur la carte graphique louée (`visite360 carte-serveur`).

Il reçoit une vue et une consigne du serveur du projet, fait calculer le modèle et rend l'image.
Trois garanties :

- la vue reste en mémoire : elle n'est écrite sur aucun disque de la carte, ni avant ni après le
  calcul ;
- seul le serveur du projet peut lui parler : un secret partagé est exigé, et la carte n'est
  atteignable que par le réseau privé ;
- elle se supprime elle-même après un temps sans demande, pour ne plus être facturée.

Le modèle (FLUX.2 klein 4B par diffusers, sur NVIDIA) n'est importé que sur la carte : ni torch ni
diffusers ne sont des dépendances du projet. Ils sont installés dans l'image système de la carte
(`docs/generation.md`).
"""

from __future__ import annotations

import hmac
import json
import os
import sys
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, TextIO

import numpy as np

from visite360 import carte, generation
from visite360.opencv import load_cv2

METADATA_URL = "http://169.254.42.42/conf?format=json"
WATCH_S = 15

Model = Callable[[np.ndarray, str, int], np.ndarray]


class DiffusersModel:
    """FLUX.2 klein 4B sur la carte NVIDIA, chargé une fois puis gardé tant que la carte vit.

    Non essayé au moment de l'écriture (pas de carte disponible) : la classe `Flux2KleinPipeline`
    et ses paramètres suivent la fiche du modèle. Voir `docs/generation.md`.
    """

    def __init__(self) -> None:
        import torch  # noqa: PLC0415 (seulement sur la carte)
        from diffusers import Flux2KleinPipeline  # type: ignore[import-not-found]  # noqa: PLC0415

        self.torch = torch
        # Les cartes d'avant 2020 (P100 du RENDER-S) ne calculent pas bien en bfloat16.
        major, _ = torch.cuda.get_device_capability()
        dtype = torch.bfloat16 if major >= 8 else torch.float16
        self.pipeline = Flux2KleinPipeline.from_pretrained(
            generation.REPOSITORY, revision=generation.REVISION, torch_dtype=dtype
        ).to("cuda")

    def __call__(self, image: np.ndarray, prompt: str, seed: int) -> np.ndarray:
        from PIL import Image  # noqa: PLC0415

        picture = Image.fromarray(image[:, :, ::-1])
        generator = self.torch.Generator("cuda").manual_seed(seed)
        result = self.pipeline(
            image=picture,
            prompt=prompt,
            height=generation.VIEW_SIZE,
            width=generation.VIEW_SIZE,
            num_inference_steps=generation.STEPS,
            generator=generator,
        ).images[0]
        return np.asarray(result)[:, :, ::-1].copy()


class Worker:
    """État de la carte : une génération à la fois, et l'heure de la dernière demande."""

    def __init__(
        self,
        model: Model,
        secret: str,
        idle_s: float,
        on_idle: Callable[[], None],
        clock: Callable[[], float] = time.monotonic,
        out: TextIO = sys.stderr,
    ) -> None:
        self.model = model
        self.secret = secret
        self.idle_s = idle_s
        self.on_idle = on_idle
        self.clock = clock
        self.out = out
        self.lock = threading.Lock()
        self.last = clock()
        self.server: ThreadingHTTPServer | None = None

    def authorized(self, header: str) -> bool:
        expected = f"Bearer {self.secret}"
        return bool(self.secret) and hmac.compare_digest(header.encode(), expected.encode())

    def generate(self, body: Mapping[str, Any]) -> dict[str, Any]:
        try:
            seed = int(body["graine"])
            prompt = str(body["consigne"])
            image = carte.decode_png(str(body["image"]))
        except (KeyError, TypeError, ValueError):
            raise carte.CarteError("Demande incomplète (image, consigne et graine).") from None
        with self.lock:
            self.last = self.clock()
            try:
                generated = self.model(image, prompt, seed)
            finally:
                self.last = self.clock()
        return {"image": carte.encode_png(generated)}

    def idle(self) -> bool:
        """Vrai si personne n'a rien demandé depuis `idle_s` et qu'aucun calcul n'est en cours."""
        if self.lock.locked():
            return False
        return self.clock() - self.last >= self.idle_s

    def watch(self) -> None:
        """Surveille l'inactivité, puis supprime la carte et arrête le serveur."""
        while self.server is not None:
            time.sleep(WATCH_S)
            if self.idle():
                print("Carte inactive : suppression de l'instance.", file=self.out, flush=True)
                try:
                    self.on_idle()
                finally:
                    server = self.server
                    self.server = None
                    if server is not None:
                        server.shutdown()
                return


def make_server(worker: Worker, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "visite360-carte"
        sys_version = ""

        def do_GET(self) -> None:
            if self.path == "/sante":
                self._json(200, {"pret": True})
            else:
                self._json(404, {"message": "Introuvable."})

        def do_POST(self) -> None:
            if self.path != "/generer":
                self._json(404, {"message": "Introuvable."})
                return
            if not worker.authorized(self.headers.get("Authorization", "")):
                self._json(403, {"message": "Accès refusé."})
                return
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._json(411, {"message": "Taille de la requête absente."})
                return
            if length > carte.MAX_BODY:
                self._json(413, {"message": "Vue trop grosse."})
                return
            try:
                body = json.loads(self.rfile.read(length))
                self._json(200, worker.generate(body))
            except (carte.CarteError, generation.GenerationError, ValueError) as error:
                self._json(400, {"message": str(error)})
            except Exception as error:  # noqa: BLE001  (le modèle peut échouer de mille façons)
                print(f"Erreur du modèle : {error!r}", file=worker.out, flush=True)
                self._json(500, {"message": "Le modèle a échoué sur la carte."})

        def _json(self, status: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # rien sur les demandes : ni consigne ni vue dans les journaux

    return ThreadingHTTPServer((host, port), Handler)


def own_id() -> str:
    """Identifiant de cette instance, donné par le service de métadonnées de Scaleway."""
    with urllib.request.urlopen(METADATA_URL, timeout=5) as response:
        return str(json.loads(response.read())["id"])


def run(environ: Mapping[str, str] | None = None, out: TextIO = sys.stderr) -> int:
    environ = environ if environ is not None else os.environ
    try:
        settings = carte.from_env(environ)
        if settings is None:
            print("Carte non configurée (VISITE360_CARTE_IMAGE absent).", file=out)
            return 1
        provider = carte.ScalewayProvider(settings)
        identifier = own_id()
        load_cv2()
        model = DiffusersModel()
    except (carte.CarteError, OSError, ImportError, generation.GenerationError) as error:
        print(f"Erreur : {error}", file=out)
        return 1
    worker = Worker(
        model, settings.worker_secret, settings.idle_s, lambda: provider.delete(identifier), out=out
    )
    server = make_server(worker, "0.0.0.0", settings.port)  # noqa: S104 (réseau privé seulement)
    worker.server = server
    threading.Thread(target=worker.watch, daemon=True).start()
    print(f"Carte prête sur le port {settings.port}.", file=out, flush=True)
    server.serve_forever()
    return 0
