# photo-resize 작업 규칙

기능 명세(정본): `D:\my\ReadBooksProject\docs\프로젝트_포트폴리오\PRD_photo-resize_20261016.md` (v0.1 Windows판 §3·§4·§8).
실제로 겪은 문제와 원인: [docs/LESSONS.md](docs/LESSONS.md). **문제를 고치면 증상·원인·해결·재발 방지를 LESSONS에 더한다.**
본보기 저장소 `D:\my\photo-organizer`는 읽기만 한다(같은 라이브러리·같은 새 버전 확인 구조).

## 바꾸지 않는 약속

- 원본에는 아무것도 쓰지 않는다. 결과는 `_small` 폴더나 `이름_small`, 이름이 있으면 ` (2)`. 결과 파일은 `.part`에 `xb`(배타적 생성)로 쓰고 `os.rename`(덮어쓰지 않음)으로 옮긴다.
- 결과가 원본보다 작지 않으면 만들지 않는다(`small`). 목표에 못 들어가면 `over`로 가장 작은 것을 둔다.
- 위치 정보는 항상 지운다: EXIF GPS IFD와 0th의 GPSTag 포인터, XMP 전체. 이미지 `info`는 비우고 exif·icc만 명시해서 넘긴다. 회전은 픽셀에 반영하고 Orientation=1, 촬영 날짜·ICC 유지, 수정 시각은 원본과 같게.
- 목표 용량은 1KB=1000바이트. 품질 탐색 범위 60~95, 60으로도 크면 긴 변을 줄인다(0.85배 이하 단계, `MIN_EDGE`·`TIME_LIMIT`에서 멈춤).
- 새 버전 확인(`update_check.py`)은 slug `photoresize`·버전·`win`만 보내고, `updateAvailable`이 불리언 true일 때만 창 아래 한 줄, url은 `https://chaekgalpi.co.kr/`로 시작할 때만 연다. 작업 스레드는 Tk 객체를 쥐지 않는다.

## 코드 규칙

- GUI와 CLI가 함께 쓰는 처리는 전부 `shrink.py`. 화면 문구는 전부 `lang/*.json`(ko·en 같은 키·같은 치환자). 언어는 파일만 더하면 늘어난다(`i18n.available_langs`).
- 배경 스레드(추정·미리보기·실행)는 모듈 함수로 두고 `queue`에 튜플만 넣는다. Tk 쪽이 `after(POLL_MS)`로 꺼낸다. 창을 닫을 때는 모든 배경 스레드를 기다린다.
- 위젯을 버릴 때(언어 바꾸기, 방법 바꾸기, 닫기)는 `_collect_now()`로 주 스레드에서 gc. 순환 참조 속 Tk 변수가 작업 스레드의 gc에서 풀리면 오류다(LESSONS L1).
- HEIC는 **pi-heif**(읽기 전용, x265 없음)로만 읽는다. pillow-heif는 시험 샘플을 쓰는 데만(`make_samples.save_heic`, 플러그인 등록 금지). exe에 pillow_heif·libx265가 없는지 빌드 뒤 목록으로 확인(LESSONS L6).
- 칩(목표 용량·방법·결과 위치·배율)은 `ChipGroup`. sv-ttk의 `Toolbutton` 라디오는 선택 상태를 안 보여 준다(LESSONS L2).
- 코드 속 비ASCII 문자열은 언어 이름과 글꼴 이름(`theme.MALGUN`, `\u` 이스케이프)뿐. 시험이 검사한다.

## 검증 순서

1. `python -m pytest tests -q` (3.14와 3.12 둘 다). 엔진을 바꿨으면 `PHOTO_RESIZE_FUZZ_SEEDS=200`으로 퍼징도(실패한 씨앗은 `-k seed17`로 재현). 끝에 `outside calls attempted during the run: 0`을 확인한다. conftest가 `check_async`·`fetch`의 기본 인자, `urlopen`, 소켓 연결을 모두 막는다.
2. 화면을 바꾸면 하네스로 찍어 직접 본다: 기본 크기와 최소 크기(`theme.WINDOW_MIN`), ko·en, 빈 목록·실행 끝·새 버전 알림. 설정 저장은 막고(`prefs.save`), 새 버전 응답은 가짜로.
3. 사진은 `samples/make_samples.py`로 만든 것만 쓴다. 사용자 사진 폴더에서 돌리지 않는다.

## 빌드 (Windows)

- PowerShell에서 `& "$env:ComSpec" /c "D:\my\photo-resize\build.bat"`. 먼저 `Get-Process photo-resize`로 사용자가 켜 둔 exe가 없는지 본다.
- 빌드한 exe 점검은 설정 파일이 없는 임시 폴더에 복사해서, `HTTP_PROXY`·`HTTPS_PROXY`를 죽은 주소(`http://127.0.0.1:9`)로 두고 띄운다(운영 서버를 치지 않게). 실서버 확인은 릴리스 때 1회만, 건수를 적는다.
- 커밋·푸시·릴리스·GitHub 저장소 만들기는 사장님이 이 세션에서 직접 지시할 때만.
