# Ressources pour comprendre les étapes

Le but n'est pas d'apprendre à coder ces algorithmes, mais de savoir juger un résultat : reconnaître un échec et en deviner la cause. Chaque pull request explique aussi son étape en clair (décision D18).

Presque tout est en anglais, sauf le TP de l'ENSTA.

## L'essentiel, environ deux heures

| Quand | Ressource | Pourquoi |
|---|---|---|
| Avant l'étape 2 | [First Principles of Computer Vision](https://fpcv.cs.columbia.edu/), Shree Nayar (Columbia) : module « Image Stitching » | Homographie, élimination des mauvaises correspondances (RANSAC), déformation et fusion des images. C'est le cœur de l'assemblage d'un panorama. |
| Avant l'étape 7 | [Démo en ligne de SAM 2](https://sam2.metademolab.com/) (Meta) | Cliquer sur un mur dans ses propres photos pour voir ce que donne la sélection. |
| Avant l'étape 9 | [« But how do AI images and videos actually work? »](https://www.3blue1brown.com/lessons/diffusion-models/), Welch Labs sur 3Blue1Brown (2025) | Comment fonctionnent les modèles de diffusion, la famille des modèles d'édition d'image. |

## Pour approfondir, si besoin

### Étapes 2 à 4 : assembler un panorama

- [TP « Homographie »](https://perso.ensta-paris.fr/%7Emanzaner/Cours/ROB317/TP1_Homographie.pdf), cours Vision 3D de l'ENSTA Paris (2023), en français : calculer une homographie et assembler deux photos, en Python avec OpenCV.
- [Tutoriel OpenCV sur l'assemblage](https://docs.opencv.org/5.0/tutorials/others/stitcher.html) : ses options donnent la liste des étapes d'un assemblage.
- [Brown et Lowe, « Automatic Panoramic Image Stitching using Invariant Features » (2007)](https://courses.cs.washington.edu/courses/cse576/07sp/notes/ijcv2007.pdf) : l'article dont s'inspire l'assemblage d'OpenCV.
- [Paul Bourke, conversion entre panorama et vue normale](https://paulbourke.net/panorama/sphere2persp) : découper une vue normale dans un panorama 360°, puis l'y remettre, sans équations.

### Étape 7 : sélectionner une surface

- [Article de recherche sur SAM 2](https://arxiv.org/abs/2408.00714) et [dépôt officiel](https://github.com/facebookresearch/sam2).

### Étape 10 : dimensions des pièces

- [HorizonNet](https://arxiv.org/abs/1901.03861) : comment un modèle retrouve la forme d'une pièce à partir d'un panorama.

### Étape 9 : IA générative et réentraînement

- [« The Illustrated Stable Diffusion », Jay Alammar](https://jalammar.github.io/illustrated-stable-diffusion/) (2022) : le mécanisme de base, en schémas.
- [Cours Diffusion de Hugging Face](https://huggingface.co/learn/diffusion-course) : gratuit, avec du code. Demande des bases en Python et PyTorch.
- [Guide des adaptateurs de Hugging Face](https://huggingface.co/docs/peft/conceptual_guides/adapter) : l'introduction explique la LoRA. [Article original](https://arxiv.org/abs/2106.09685).
- [Rapport technique de Qwen-Image](https://arxiv.org/pdf/2508.02324) : avancé.

### Référence générale

- [Szeliski, « Computer Vision: Algorithms and Applications », 2e édition (2022)](https://link.springer.com/10.1007/978-3-030-34372-9), chapitre 8 « Image Alignment and Stitching ».

Liens vérifiés le 2026-10-24.
