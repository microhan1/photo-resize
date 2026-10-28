# Third-party licenses / 함께 묶인 라이브러리의 라이선스

The source code of this repository is MIT (see `LICENSE`). The released single-file
`photo-resize.exe` (PyInstaller) also contains the libraries below, each under its own
license. HEIC photos are read with **pi-heif**, the read-only build of pillow-heif: it has
no HEVC encoder, so the GPLv2 **x265 is not in the exe**. The HEVC decoder (libde265) and
libheif that remain are **LGPL-3.0**; how this exe meets the LGPL is explained below.

이 저장소의 코드는 MIT입니다. 배포하는 exe에는 아래 라이브러리가 함께 들어 있고, 각자 자기
라이선스를 따릅니다. HEIC는 저장 기능을 뺀 읽기 전용판 **pi-heif**로 읽습니다. HEVC 인코더가
없어 **GPLv2인 x265는 exe에 들어 있지 않습니다**. 남는 libheif·libde265는 **LGPL-3.0**이며,
이 exe가 LGPL 조건을 지키는 방법은 아래에 적었습니다.

Versions are those of the v0.1.0 build (2026-10-16), read from the installed packages;
the v0.1.1 build (2026-10-26) carries the same versions (checked again), and so does
the v0.1.2 build (2026-10-27, checked again) and the v0.1.3 build (2026-10-28, checked again).

## pi-heif 1.4.0 and the libraries in its Windows wheel

| Library | Version | License | Source |
| --- | --- | --- | --- |
| pi-heif | 1.4.0 | BSD-3-Clause (its own code); the binary wheel as a whole: LGPL-3.0 | https://github.com/bigcat88/pillow_heif (pi-heif is built from it) · https://pypi.org/project/pi-heif/1.4.0/ |
| libheif | 1.23.0 | LGPL-3.0 | https://github.com/strukturag/libheif |
| libde265 (HEVC decoder) | 1.1.1 | LGPL-3.0 | https://github.com/strukturag/libde265 |
| MinGW-w64 runtime (libgcc_s_seh, libstdc++) | — | GPL-3.0 with the GCC Runtime Library Exception (allows use in programs under any license) | https://www.mingw-w64.org/ |
| MinGW-w64 libwinpthread | — | MIT and BSD | (same) |

The versions are what the libraries report at run time (`pi_heif.libheif_info()`); the
wheel's own `LICENSES_bundled.txt` still names libheif 1.18.1 and libde265 1.0.15. No x265
DLL is in the wheel or in the exe, and libheif's import table names no x265 (checked
2026-10-16).

### The LGPL-3.0 libraries in a single-file exe

- They stay separate DLLs (`libheif-*.dll`, `libde265-*.dll`) inside the exe; PyInstaller
  unpacks them to a temporary folder at start and the program loads them from there.
- You may replace them: this repository holds the complete source of the program and its
  build script (`build.bat`), so the exe can be rebuilt with a modified or newer libheif /
  libde265 (install another pi-heif wheel, or put your own DLLs in its place, and build).
- The program's own license (MIT) allows modifying it and reverse engineering for
  debugging such modifications, as LGPL-3.0 section 4 asks.
- The license texts come with the program, in `licenses/` (repository and exe):
  `LGPL-3.0.txt`, `GPL-3.0.txt` (the GNU GPL 3.0 that the LGPL 3.0 builds on) and
  `GCC-RUNTIME-LIBRARY-EXCEPTION-3.1.txt`.
- Source of the LGPL parts: the links above (libheif, libde265), and pi-heif's source
  distribution on PyPI. Questions: the GitHub issues of this repository.

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

The full texts are in Pillow's `LICENSE` file (installed as `pillow-*.dist-info/licenses/LICENSE`, also inside the exe).

## Others

| Library | License | Source |
| --- | --- | --- |
| piexif 1.1.3 | MIT | https://github.com/hMatoba/Piexif |
| sv-ttk 2.6.1 (Sun Valley theme) | MIT | https://github.com/rdbende/Sun-Valley-ttk-theme |
| tkinterdnd2 0.6.3 (with tkdnd) | MIT (tkinterdnd2), BSD-style (tkdnd) | https://github.com/Eliav2/tkinterdnd2 |
| Python 3 | PSF License | https://www.python.org/ |
| Tcl/Tk | Tcl/Tk License (BSD-style) | https://www.tcl.tk/ |
| PyInstaller bootloader | GPL-2.0 with the PyInstaller bootloader exception (allows any license for the bundled program) | https://github.com/pyinstaller/pyinstaller |

pillow-heif (whose binary wheel contains x265, GPLv2) is used only by the test suite to
write HEIC samples; it is not part of the program or the exe.
