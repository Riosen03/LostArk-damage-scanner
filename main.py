import cv2          # openCV
import numpy as np  # numpy
import mss          # 화면 캡처
import easyocr      # OCR 라이브러리
import re           # 정규표현식(문자열 필터링) 라이브러리
import time         # 시간 측정을 위한 time 모듈
import collections  # 최빈값 계산
import sqlite3      # DB(SQLite)

# SQLite DB 초기화 및 테이블 생성 함수
def init_db():
    conn = sqlite3.connect('damage_data.db')
    cursor = conn.cursor()
    # 지능, 특화, 무공, 총 공격력, 데미지, 수집시간을 저장하는 단일 테이블
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS damage_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            intelligence INTEGER,
            specialty INTEGER,
            weapon_atk INTEGER,
            total_atk INTEGER,
            damage_value INTEGER
        )
    ''')
    conn.commit()
    return conn

# 스테이터스 입력 (Console)
print("=== [로스트아크 데미지 데이터 수집기] ===")
print("데이터 수집을 위한 현재 캐릭터 스테이터스 입력")
intelligence = int(input("현재 지능 수치: "))
weapon_atk = int(input("현재 무기 공격력: "))
total_atk = int(input("현재 총 공격력: "))
specialty = int(input("현재 특화 수치: "))

# CLI에서 입력이 번거로울 때 코드 직접 수정용
# intelligence = 6407
# weapon_atk = 2938
# total_atk = 1790
# specialty = 160

# =================================================================================
# [OCR Load Part]
# 숫자만 read -> 'en'(영어) 모델만 로드
reader = easyocr.Reader(['en']) 
print("OCR 로드 완료")

# 상태 기억 변수를 버퍼(리스트) 형태로 저장
session_damages = [] # 검수를 위해 데미지만 임시로 모아둘 리스트
damage_buffer = []
last_detect_time = time.time()
# =================================================================================


# 화면 캡처를 위한 mss 객체 생성
with mss.mss() as sct:
    # =================================================================================
    # [ROI Part]

    # ROI 지정
    monitor = {"top": 250, "left": 600, "width": 800, "height": 600}    # 해당 위치는 직접 조절 필요
    print("종료 - 'q'")

    # 실시간 캡처 무한 루프 
    while True:
        # 지정된 ROI 캡처 
        sct_img = sct.grab(monitor)

        # 캡처된 화면을 NumPy 배열로 변환 / BGRA 포맷을 OpenCV 처리를 위해 BGR 포맷으로 변환 (알파 채널 제거)
        img_bgr = cv2.cvtColor(np.array(sct_img), cv2.COLOR_BGRA2BGR)
    # =================================================================================


        # =================================================================================
        # [Preprocessing Part]

        # BGR을 HSV 색상 공간으로 변환
        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

        # 크리티컬 폰트(노란색)의 HSV 범위 지정
        lower_yellow = np.array([15, 150, 150])
        upper_yellow = np.array([35, 255, 255])

        # 노란색 영역만 흰색(255), 나머지는 검은색(0)으로 만드는 마스크 생성
        mask = cv2.inRange(hsv, lower_yellow, upper_yellow)

        # Morphology
        # 3x3 kernel 생성
        kernel = np.ones((3, 3), np.uint8)
        
        # Closing 연산 -> antialiasing 테두리 복원 및 틈새 메우기
        mask_cleaned = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        
        # 윤곽선 검출 & bounding 박스
        # 마스크 이미지에서 흰색 덩어리들의 외곽선(Contours) 찾기
        contours, _ = cv2.findContours(mask_cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # 원본 이미지에 박스를 그리기 위해 복사본 생성
        img_result = img_bgr.copy()

        # 유효한 윤곽선(숫자 조각)들의 좌표를 담을 리스트
        valid_rects = []

        for cnt in contours:
            # 면적이 50 픽셀 이상인 덩어리(노이즈 제외)만 수집
            if cv2.contourArea(cnt) > 50:
                valid_rects.append(cv2.boundingRect(cnt))

        # 유효한 숫자 조각이 하나라도 발견되었다면 (데미지가 떴다면)
        if valid_rects:
            # 모든 조각을 포함하는 가장 바깥쪽 좌표 계산
            min_x = min([x for x, y, w, h in valid_rects])
            min_y = min([y for x, y, w, h in valid_rects])
            max_x = max([x + w for x, y, w, h in valid_rects])
            max_y = max([y + h for x, y, w, h in valid_rects])

            # 원본 확인용 창에 거대한 하나로 합쳐진 초록색 박스 그리기
            cv2.rectangle(img_result, (min_x, min_y), (max_x, max_y), (0, 255, 0), 2)

            # OCR에 넘겨주기 위해 mask(흑백) Crop
            # 글자가 테두리에 너무 딱 붙지 않도록 Padding
            pad = 5
            crop_y1 = max(0, min_y - pad)
            crop_y2 = min(mask_cleaned.shape[0], max_y + pad)
            crop_x1 = max(0, min_x - pad)
            crop_x2 = min(mask_cleaned.shape[1], max_x + pad)

            # 최종적으로 잘라낸 흑백 숫자 이미지
            final_crop = mask_cleaned[crop_y1:crop_y2, crop_x1:crop_x2]
        # =================================================================================


        # =================================================================================
        # [text OCR Part]

            # 크롭된 배열이 비어있지 않은 경우에만 OCR 수행
            if final_crop.size > 0:
                # OCR로 크롭된 이미지 읽기 (detail=0은 텍스트 문자열만 리스트로 반환함)
                ocr_result = reader.readtext(final_crop, detail=0)
           
            if ocr_result:
                # 인식된 결과 리스트를 하나의 문자열로 합치기
                raw_text = "".join(ocr_result)

                # 정규표현식을 사용하여 숫자(0-9)가 아닌 모든 문자(알파벳, 쉼표 등) 제거
                # "306,867"을 "306867"로 정제(, 제거)
                clean_number = re.sub(r'[^0-9]', '', raw_text)

                # 버퍼 수집
                # 자잘한 1~3자리 노이즈는 무시하고, 4자리 이상의 유의미한 데미지만 바구니에 담기
                if clean_number and len(clean_number) >= 4:
                    damage_buffer.append(clean_number)
                    last_detect_time = time.time() # 숫자가 마지막으로 목격된 시간 갱신
        
        # 화면에서 숫자가 안 보인지 0.1초가 지났고(대기시간 0.1초), 바구니(버퍼)에 수집된 데이터가 있다면?
        if (time.time() - last_detect_time) > 0.1 and len(damage_buffer) > 0:
            
            # 수집된 숫자들 중 '가장 많이 등장한 숫자'를 찾음 (noise)
            counter = collections.Counter(damage_buffer)
            final_damage = counter.most_common(1)[0][0]
            
            # DB에 바로 넣지 않고 세션 리스트에 임시 저장
            session_damages.append(final_damage)
            print(f"타격 인식 : {final_damage} (현재 수집량: {len(session_damages)}개)")
            
            # 다음 타격을 위해 바구니를 깨끗하게 비우기
            damage_buffer.clear()
        # =================================================================================


        # 화면 출력
        # cv2.imshow('Original ROI', img_bgr)       
        # cv2.imshow('Yellow Mask', mask_cleaned)
        cv2.imshow('Bounding Box Result', img_result)

        # 'q' 키를 누르면 수집 종료
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break


# =================================================================================
# [data saving Part]
# 루프 종료 후 열려있는 OpenCV 창 모두 닫기
cv2.destroyAllWindows()

# 수집 데이터 출력, 검수 및 DB 최종 적재
print("수집 종료. 데이터를 검수합니다.")

while True:
    print("\n" + "="*40)
    print(f"수집 리스트 - 총 {len(session_damages)}개의 데미지 데이터")
    print("-" * 40)
    
    # 리스트가 비어있으면 즉시 종료
    if len(session_damages) == 0:
        print("수집된 (또는 남은) 데이터가 없습니다. 프로그램을 종료합니다.")
        break

    # 세로로 번호(인덱스)를 붙여서 출력
    for i, dmg in enumerate(session_damages):
        print(f"[{i}] : {dmg}")
    print("="*40)

    # 저장, 수정, 취소 선택
    action = input("\n작업을 선택하세요. - 현 리스트 저장(y) / 일부 삭제(m) / 전체 취소(n) : ").lower()

    # 저장 
    if action == 'y':
        conn = init_db()
        cursor = conn.cursor()
        
        # DB에 적재할 튜플 리스트 생성 (입력받은 스탯 포함)
        db_records = [
            (intelligence, specialty, weapon_atk, total_atk, dmg) 
            for dmg in session_damages
        ]
        
        # executemany -> Batch Insert
        cursor.executemany('''
            INSERT INTO damage_logs (intelligence, specialty, weapon_atk, total_atk, damage_value)
            VALUES (?, ?, ?, ?, ?)
        ''', db_records)
        
        conn.commit()
        conn.close()

        # DB 저장 후 루프 break 및 프로그램 종료
        print(f"\n성공적으로 {len(session_damages)}개의 데이터가 'damage_data.db'에 저장되었습니다.")
        break

    # 삭제 
    elif action == 'm':
        while True:
            del_input = input("\n삭제할 데이터의 번호(인덱스)를 쉼표(,)로 구분하여 입력하세요 (예: 2, 5, 11) \n삭제 작업을 취소하려면 'c'를 입력하세요: ")
            
            if del_input.lower() == 'c':
                break 

            try:
                # 입력받은 문자열을 정수 리스트로 변환(쉼표(,)기준 split, 공백제거)한 뒤, set()을 씌워 중복 입력 방지
                raw_indices = [int(idx.strip()) for idx in del_input.split(',')]
                del_indices = list(set(raw_indices))

                # 인덱스가 꼬이지 않도록 내림차순으로 정렬해서 삭제
                del_indices.sort(reverse=True)
                
                for idx in del_indices:
                    if 0 <= idx < len(session_damages):
                        removed_val = session_damages.pop(idx)
                        print(f"[-] 번호 [{idx}] 데이터 ({removed_val}) 삭제 완료")
                    else:
                        print(f"[!] 번호 [{idx}] 존재하지 않는 인덱스 > 무시")
                # 수정 후 다시 while 루프
                print("\n데이터가 수정되었습니다. 수정된 리스트로 다시 작업을 선택합니다.")
                break

            except ValueError:
                print("\n입력 형식이 잘못되었습니다. 숫자와 쉼표(,)만 입력해주세요.")

    # 취소      
    elif action == 'n':
        print("\n저장 취소. 수집된 모든 데이터가 폐기되었습니다.")
        break # 루프 탈출 및 프로그램 종료

    # 오입력
    else:
        print("\n올바른 명령어(y, m, n)를 입력해주세요.")
# =================================================================================