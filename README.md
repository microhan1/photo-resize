# 사진 용량 줄이기 (Photo Resize)

<img src="assets/icon.png" width="96" alt="icon">

[English](README.en.md)

> **사진은 어디에도 올라가지 않습니다.** 내 PC 안에서만 줄입니다(새 버전 확인만 예외 — 도구 이름·버전만, 하루 한 번, 끌 수 있음).
> **원본은 그대로 둡니다.** 결과는 `_small` 폴더에 새로 만듭니다.
> **위치 정보(GPS)는 항상 지웁니다.**

사진을 끌어다 놓고 **"500KB 이하"처럼 목표 용량을 고르면, 그 안에 들어가는 가장 좋은 화질로** 한 장씩 자동으로 줄여 주는 Windows 프로그램입니다. 채용·민원·학교·쇼핑몰 사이트의 "1MB 이하" 업로드 한도, 메일 첨부, 단톡방 올리기에 맞춥니다. 여러 장·폴더째 한 번에, 아이폰 HEIC 도 받습니다.

![프로그램 화면](docs/screenshot.png)

## 다운로드

- **실행 파일**: [Releases](https://github.com/microhan1/photo-resize/releases)에서 `photo-resize.exe`를 받아 더블클릭. 설치가 필요 없습니다. (서명되지 않은 exe라 SmartScreen 경고가 뜨면 "추가 정보 → 실행")
- **소스 실행** (Python 3.12 이상):

```bash
pip install -r requirements.txt
python main.py
```

## 사용법

1. 사진이나 폴더를 창에 끌어다 놓습니다(또는 **사진 추가… / 폴더 추가…**).
2. 오른쪽에서 줄이는 방법을 고릅니다. 기본은 **목표 용량 500KB**. 표와 오른쪽 아래에 예상 크기가 바로 나옵니다(앞 3장을 실제로 줄여 본 값). 표에서 한 장을 고르면 원본과 결과를 같은 배율로 나란히 봅니다(100%·200%·400%로 확대하고 끌어서 옮기기).
3. **줄이기**를 누릅니다. 끝나면 "7장 · 9.1 MB → 2.3 MB · 위치 정보 지움 6장"처럼 요약이 나오고, **결과 폴더 열기**로 바로 엽니다.

| 방법 | 고르는 것 | 하는 일 |
| --- | --- | --- |
| **목표 용량** (기본) | 200KB · 500KB · 1MB · 2MB · 직접 입력 | 한 장마다 목표 이하에서 **가장 높은 화질**을 찾습니다. 품질(95→60)을 먼저 낮추고, 품질 60으로도 크면 긴 변을 줄입니다. |
| 크기 | 긴 변 3840 · 2560 · 1920 · 1280 · 800px | 비율을 지키며 줄입니다(더 키우지는 않음). 품질 85. |
| 품질만 | 높음 85 · 보통 75 · 작게 60 | 픽셀 크기는 그대로, 저장 공간 정리용. |

- 목표 용량은 1KB = 1000바이트로 셉니다. 사이트가 1024로 세든 1000으로 세든 넘지 않습니다.
- 끝까지 줄여도 목표에 못 들어가는 사진(아주 작은 목표)은 **목표 초과**로 표시하고 가장 작게 만든 결과를 둡니다.
- 결과가 **원본보다 커지면 만들지 않고** "이미 작음"으로 표시합니다.

## 결과는 어디에

| 결과 위치 | 예 |
| --- | --- |
| `_small` 폴더에 (기본) | `여행\day1\IMG_1.jpg` → `여행\_small\day1\IMG_1.jpg` (폴더 구조 유지) |
| 이름 뒤 `_small` | `여행\day1\IMG_1.jpg` → `여행\day1\IMG_1_small.jpg` |

- 원본은 절대 덮어쓰지 않습니다. 같은 이름이 있으면 `IMG_1 (2).jpg`처럼 번호를 붙입니다(이미 있는 파일·폴더는 건드리지 않음).
- 결과는 JPG입니다. 투명한 PNG는 흰 바탕으로 합쳐 JPG로 만들고, **투명한 PNG는 PNG로**를 켜면 투명을 살려 PNG로 둡니다(대신 줄어드는 폭이 작습니다). 화면 캡처처럼 투명한 곳이 실제로 없는 PNG는 켜 두어도 JPG로 만듭니다.
- 다시 돌려도 `_small` 폴더와 `_small` 이 붙은 파일은 입력으로 읽지 않습니다.
- 받는 형식: JPG · PNG · HEIC/HEIF · WebP · BMP · TIFF.

## 사진 정보(EXIF)

| 정보 | 결과 |
| --- | --- |
| 위치(GPS) | **항상 지움** (EXIF의 GPS와, 위치가 들어 있을 수 있는 XMP 정보) |
| 회전 | 사진을 실제로 돌려 저장 — 다른 곳에 올려도 옆으로 눕지 않습니다 |
| 촬영 날짜·카메라 | 그대로 |
| 색 프로필(ICC) | 그대로 (아이폰 Display P3 포함) |
| 파일 수정 시각 | 원본과 같게 (날짜순 정렬이 어긋나지 않게) |

## 명령줄

```bash
python main.py D:\사진 --target 1MB
python main.py D:\사진\a.jpg D:\사진\b.heic --mode size --size 1920 --output suffix
python main.py D:\사진 --mode quality --quality medium --no-recursive
```

옵션: `--mode target|size|quality`, `--target 500KB`, `--size 1920`, `--quality high|medium|low|60~95`, `--output folder|suffix`, `--keep-png`, `--no-recursive`, `--lang ko|en`, `--version`. 종료 코드: 0 성공, 1 일부 실패, 2 줄일 사진 없음.

## 새 버전 확인

실행할 때 새 버전이 있는지 확인하려고 도구 이름(`photoresize`)과 버전만 책갈피 서버(chaekgalpi.co.kr)에 보냅니다. 파일·사진은 보내지 않고, 하루 한 번만 확인하며, 오른쪽 위 **새 버전 확인**을 끄면 묻지 않습니다. 확인은 창이 뜬 뒤 백그라운드에서 하고, 연결이 안 되면 아무것도 표시하지 않습니다.

새 버전이 있으면 창 아래에 한 줄 알림이 나옵니다. **업데이트**를 누르면 책갈피 툴 페이지가 열리고, **다음에**를 누르면 그 버전은 다시 알리지 않습니다. 자동으로 내려받거나 바꾸지 않습니다.

![새 버전 알림 줄](docs/update_notice.png)

*그림: 알림 줄 화면. 서버 응답을 가짜(새 버전 0.2.0)로 넣어 띄운 시험 화면입니다.*

## 의견 보내기

안 되는 것·불편한 것·바라는 기능은 프로그램 오른쪽 위 **의견 보내기**를 누르거나 <https://chaekgalpi.co.kr/tools/photoresize#feedback> 에서 로그인 없이 보낼 수 있습니다. 누르면 브라우저로 그 페이지가 열릴 뿐, 프로그램이 직접 보내는 것은 없습니다(열리는 주소에 프로그램 버전이 붙습니다). [GitHub Issues](https://github.com/microhan1/photo-resize/issues)도 그대로 받습니다.

![창 오른쪽 위의 의견 보내기](docs/feedback_link.png)

*그림: 창 오른쪽 위. 「의견 보내기」 · 「새 버전 확인」 · 언어 선택.*

## 하지 않는 것

- 동영상은 줄이지 않습니다.
- AI 화질 높이기, 배경 지우기, 증명사진 규격 맞추기, 이름 바꾸기, 자르기·보정 같은 편집은 하지 않습니다.
- WebP로 저장하지 않습니다(올리는 사이트가 받지 않는 경우가 많아 v0.2 후보).
- 사진을 서버로 보내지 않습니다. 원본을 지우거나 덮어쓰지 않습니다.
- 새 버전을 자동으로 내려받거나 바꾸지 않습니다.

## 시리즈

- 책갈피 툴: [사진 정리](https://github.com/microhan1/photo-organizer) · [음악 폴더 정리](https://github.com/microhan1/music-folder-organizer) · [음악 정보 채우기](https://github.com/microhan1/music-tag-filler)
- [책갈피 라이브러리](https://chaekgalpi.co.kr/tools/photoresize?utm_source=github&utm_medium=referral&utm_campaign=tool_cta&utm_content=photoresize) — 읽은 책과 독서록을 기록하는 웹 서비스.

## 라이선스

이 저장소의 코드는 MIT입니다([LICENSE](LICENSE)). HEIC는 저장 기능을 뺀 읽기 전용판 **pi-heif**로 읽어, GPLv2인 x265 인코더는 `photo-resize.exe`에 들어 있지 않습니다. exe에 함께 들어가는 HEIC 해독 라이브러리 libheif·libde265는 **LGPL-3.0**입니다.

- 이 두 라이브러리는 exe 안에서도 따로 된 DLL로 남아 있습니다. 이 저장소의 소스와 `build.bat`으로 다른 버전으로 바꿔 다시 빌드할 수 있습니다.
- 라이선스 전문은 `licenses/` 폴더에(exe 안에도) 있습니다.
- 라이브러리 목록과 소스 위치: [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md)

사용한 라이브러리: Pillow, pi-heif(libheif·libde265), piexif, sv-ttk, tkinterdnd2.
