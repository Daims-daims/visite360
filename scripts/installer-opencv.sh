#!/usr/bin/env bash
# Compile OpenCV sans FFmpeg et l'installe dans l'environnement Python actif (décision D19).
#
# Le paquet opencv-python-headless publié sur PyPI embarque FFmpeg, et sur macOS les
# encodeurs x264 et x265 sous GPL. Ce script compile OpenCV depuis ses sources officielles
# avec seulement les modules utiles à visite360, sans FFmpeg ni autre bibliothèque à risque.
#
# Utilisation, environnement virtuel activé :
#   bash scripts/installer-opencv.sh           # compile si besoin, puis installe
#   bash scripts/installer-opencv.sh --force   # recompile même si le paquet existe déjà
#
# Le paquet compilé est gardé dans build/opencv/ (ignoré par git).

set -euo pipefail

OPENCV_VERSION="4.14.0.94"
PYTHON="${PYTHON:-python}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build/opencv"

force=0
for arg in "$@"; do
    case "$arg" in
        --force) force=1 ;;
        *)
            echo "Erreur : option inconnue « $arg ». Seule --force est acceptée." >&2
            exit 2
            ;;
    esac
done

if ! "$PYTHON" -m pip --version >/dev/null 2>&1; then
    echo "Erreur : « $PYTHON -m pip » ne fonctionne pas. Activer l'environnement virtuel du projet." >&2
    exit 1
fi

py_tag="$("$PYTHON" -c 'import sys; print(f"cp{sys.version_info[0]}{sys.version_info[1]}")')"
wheel="$(ls "$OUT"/opencv_python_headless-"$OPENCV_VERSION"-"$py_tag"-*.whl 2>/dev/null | head -n 1 || true)"

if [[ -z "$wheel" || "$force" == 1 ]]; then
    echo "Compilation d'OpenCV $OPENCV_VERSION sans FFmpeg (quelques minutes)..."
    mkdir -p "$OUT"
    export ENABLE_HEADLESS=1
    export CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-$(getconf _NPROCESSORS_ONLN)}"
    export CMAKE_ARGS="\
 -DBUILD_LIST=core,imgproc,imgcodecs,features2d,flann,calib3d,stitching,python3\
 -DWITH_FFMPEG=OFF -DWITH_GSTREAMER=OFF -DWITH_AVFOUNDATION=OFF -DWITH_V4L=OFF -DWITH_1394=OFF\
 -DWITH_OPENEXR=OFF -DWITH_OPENJPEG=OFF -DWITH_JASPER=OFF -DWITH_TIFF=OFF -DWITH_WEBP=OFF\
 -DWITH_AVIF=OFF -DWITH_ITT=OFF -DWITH_PROTOBUF=OFF -DWITH_EIGEN=OFF -DWITH_TBB=OFF\
 -DWITH_QT=OFF -DWITH_GTK=OFF -DWITH_VTK=OFF -DWITH_GDAL=OFF -DWITH_GDCM=OFF -DWITH_IPP=OFF\
 -DBUILD_JPEG=ON -DBUILD_PNG=ON -DBUILD_ZLIB=ON -DOPENCV_ENABLE_NONFREE=OFF\
 -DBUILD_TESTS=OFF -DBUILD_PERF_TESTS=OFF -DBUILD_EXAMPLES=OFF -DBUILD_DOCS=OFF"
    "$PYTHON" -m pip wheel --no-deps --no-binary opencv-python-headless \
        "opencv-python-headless==$OPENCV_VERSION" -w "$OUT"
    wheel="$(ls "$OUT"/opencv_python_headless-"$OPENCV_VERSION"-"$py_tag"-*.whl | head -n 1)"
else
    echo "Paquet déjà compilé : $(basename "$wheel")"
fi

# Retire toute autre variante d'OpenCV, qui serait importée à la place de celle-ci.
"$PYTHON" -m pip uninstall -y opencv-python opencv-contrib-python opencv-contrib-python-headless \
    >/dev/null 2>&1 || true
"$PYTHON" -m pip install --force-reinstall --no-deps "$wheel"

"$PYTHON" - <<'EOF'
import re
import sys

import cv2

if re.search(r"FFMPEG:\s+YES", cv2.getBuildInformation()):
    sys.exit("Erreur : l'OpenCV importé utilise encore FFmpeg. Vérifier qu'aucune autre copie n'est installée.")
print(f"OpenCV {cv2.__version__} installé, sans FFmpeg.")
EOF
