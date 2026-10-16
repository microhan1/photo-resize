# Third-party licenses / 함께 묶인 라이브러리의 라이선스

The source code of this repository is MIT (see `LICENSE`). The released single-file
`photo-resize.exe` (PyInstaller) also contains the libraries below. Because the
pillow-heif binary wheel links **x265 (GPLv2)** into libheif, the exe as a combined work is
distributed under the terms of the **GNU GPL version 2**; the MIT code of this repository
is compatible with that. Each library keeps its own license.

이 저장소의 코드는 MIT입니다. 배포하는 exe에는 아래 라이브러리가 함께 들어 있습니다.
pillow-heif 바이너리가 libheif에 x265(GPLv2)를 연결해 두었기 때문에(이 도구는 HEIC를
읽기만 하지만 libheif가 x265를 직접 불러오도록 빌드되어 있어 뺄 수 없음) **exe 전체는
GPLv2 조건으로 배포**합니다. 각 라이브러리는 자기 라이선스를 그대로 따릅니다.

Versions are those of the build environment of v0.1.0 (2026-10-16).

## pillow-heif 1.8.0 and the libraries in its Windows wheel

| Library | Version | License | Source |
| --- | --- | --- | --- |
| pillow-heif | 1.8.0 | BSD-3-Clause (source); the binary wheel: GPLv2 because of x265 | https://github.com/bigcat88/pillow_heif |
| libheif | 1.23.4 | LGPL-3.0 | https://github.com/strukturag/libheif/tree/v1.23.4 |
| libde265 (HEVC decoder) | 1.1.3 | LGPL-3.0 | https://github.com/strukturag/libde265/tree/v1.1.3 |
| x265 (HEVC encoder, linked by libheif, not used by this tool) | 4.2 / 4.3 | GPL-2.0 | https://bitbucket.org/multicoreware/x265_git/src/4.2 |
| MinGW-w64 runtime (libgcc, libstdc++) | — | GPL-3.0 with GCC Runtime Library Exception | https://sourceforge.net/p/mingw-w64/mingw-w64/ci/master/tree/COPYING |
| MinGW-w64 libwinpthread | — | MIT and BSD | (same) |

The LGPL libraries are separate DLLs inside the exe (PyInstaller unpacks them to a
temporary folder at start); they can be replaced by building the exe from this source
with other DLLs (`build.bat`). Source of the exact versions: the links above, and the
pillow-heif 1.8.0 source distribution on PyPI (https://pypi.org/project/pillow-heif/1.8.0/).
Questions about the source of the GPL/LGPL parts: the GitHub issues of this repository.

## Pillow 12.2.0 and the libraries in its Windows wheel

| Library | License |
| --- | --- |
| Pillow | MIT-CMU (HPND) — https://github.com/python-pillow/Pillow |
| libjpeg-turbo 3.1.4.1 | IJG License, BSD-3-Clause, zlib |
| libpng 1.6.56 | libpng License |
| libtiff 4.7.1 | libtiff License (BSD-like) |
| libwebp 1.6.0 | BSD-3-Clause |
| libavif 1.4.1 | BSD-2-Clause |
| openjpeg 2.5.4 | BSD-2-Clause |
| lcms2 2.18 | MIT |
| freetype 2.14.3 | FreeType License (FTL) |
| harfbuzz 13.2.1 | MIT ("Old MIT") |
| brotli 1.2.0 | MIT |
| xz 5.8.3 | 0BSD |
| zlib-ng 2.3.3 | zlib |

The full texts are in Pillow's `LICENSE` file (installed as `pillow-*.dist-info/licenses/LICENSE`).

## Others

| Library | License | Source |
| --- | --- | --- |
| piexif 1.1.3 | MIT | https://github.com/hMatoba/Piexif |
| sv-ttk 2.6.1 (Sun Valley theme) | MIT | https://github.com/rdbende/Sun-Valley-ttk-theme |
| tkinterdnd2 0.6.3 (with tkdnd) | MIT (tkinterdnd2), BSD-style (tkdnd) | https://github.com/Eliav2/tkinterdnd2 |
| Python 3 | PSF License | https://www.python.org/ |
| Tcl/Tk | Tcl/Tk License (BSD-style) | https://www.tcl.tk/ |
| PyInstaller bootloader | GPL-2.0 with the PyInstaller bootloader exception | https://github.com/pyinstaller/pyinstaller |
