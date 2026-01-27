import requests
import base64
import pandas as pd
import json
import ast
from PIL import Image   # ★ 추가 필요
from io import BytesIO  # ★ 추가 필요
from bs4 import BeautifulSoup
from requests.exceptions import HTTPError
from schema.product import ProductSchema
from urllib.parse import urljoin
from ai.model import call_ai_service

# 상품api 에서 상품정보 추출
def getProductInfo(prd_no):
    url = f"https://hapix.halfclub.com/product/products/withoutPrice/{prd_no}"

    payload = {
        "countryCd": "001",
        "langCd": "001",
        "siteCd": "1",
        "deviceCd": "001",
        "mandM": "halfclub"
    }

    try:
        response = requests.get(url, params=payload, timeout=5)
        response.raise_for_status()
        data = response.json()

        result = getPrdInfoByJson(data)
        return result
    
    except HTTPError as http_err:
        print(f"HTTP error ocurred:, {http_err}")
    except Exception as err:
        print(f"Orther error occured: {err}")

# 외부 사이트 이미지 제한정책으로 인한 이미지 로컬 다운로드 
def encode_image_to_base64(image_url):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        response = requests.get(image_url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            # 1. 이미지 데이터 로드
            img_data = response.content
            
            # ★ [Qwen 에러 방지] 이미지 크기 검사 로직 추가
            try:
                img = Image.open(BytesIO(img_data))
                width, height = img.size
                
                # 가로 또는 세로가 50px 미만이면 무시 (아이콘, 추적픽셀 등)
                if width < 50 or height < 50:
                    print(f"🚫 너무 작은 이미지 제외 ({width}x{height}): {image_url}")
                    return None
            except Exception:
                # 이미지 파일이 아니거나 손상된 경우 무시
                return None

            # 2. Base64 인코딩
            encoded_string = base64.b64encode(img_data).decode('utf-8')
            
            # 확장자 판별 (기본 jpg)
            mime_type = "image/jpeg"
            if image_url.lower().endswith(".png"):
                mime_type = "image/png"
            elif image_url.lower().endswith(".gif"):
                mime_type = "image/gif"
                
            return f"data:{mime_type};base64,{encoded_string}"
            
    except Exception as e:
        print(f"이미지 다운로드 실패: {e}")
        return None
    return None

# 이미지 chunk
def encode_image_to_base64_chunk(image_url):
    """
    이미지를 다운로드하여 Base64 리스트로 반환 (긴 이미지는 자름)
    Return: List[str] (예: ["data:...", "data:..."])
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        response = requests.get(image_url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            img_data = response.content
            
            try:
                img = Image.open(BytesIO(img_data))
                width, height = img.size
                
                # 1. 너무 작은 이미지 제외
                if width < 50 or height < 50:
                    return []

                results = []
                
                # 2. 세로로 긴 이미지 처리 (비율 1:2.5 초과)
                if height > width * 2.5:
                    chunk_height = width 
                    for y in range(0, height, chunk_height):
                        bottom = min(y + chunk_height, height)
                        box = (0, y, width, bottom)
                        cropped_img = img.crop(box)
                        
                        buffered = BytesIO()
                        if cropped_img.mode in ("RGBA", "P"):
                            cropped_img = cropped_img.convert("RGB")
                        cropped_img.save(buffered, format="JPEG")
                        
                        encoded_chunk = base64.b64encode(buffered.getvalue()).decode('utf-8')
                        results.append(f"data:image/jpeg;base64,{encoded_chunk}")
                        
                        if len(results) >= 5: break # 최대 5조각
                    return results

                # 3. 일반 이미지
                else:
                    encoded_string = base64.b64encode(img_data).decode('utf-8')
                    # 확장자 처리
                    mime_type = "image/jpeg"
                    if image_url.lower().endswith(".png"): mime_type = "image/png"
                    elif image_url.lower().endswith(".gif"): mime_type = "image/gif"
                    
                    return [f"data:{mime_type};base64,{encoded_string}"] # 리스트로 감쌈
                    
            except Exception:
                return []
    except Exception:
        return []
    return []


# json 데이터 정규화
def getPrdInfoByJson(data):
    """
    제공된 '네파' 상품 데이터 구조에 최적화된 추출 함수
    """
    
    # [1] 데이터 꺼내기 ('data' 키 안에 실제 정보가 있음)
    if isinstance(data, dict) and 'data' in data:
        raw_data = data['data']
    else:
        raw_data = data # 'data' 키가 없으면 그대로 사용

    # 데이터프레임 변환
    if isinstance(raw_data, dict):
        df = pd.DataFrame([raw_data])
    else:
        df = raw_data.copy()

    if df.empty:
        return "데이터 없음"

    # ==========================================================
    # [2] 안전한 파싱 (혹시 문자열로 되어있을 경우 대비)
    # ==========================================================
    def robust_parse(val):
        if isinstance(val, dict): return val
        if isinstance(val, list): return val # 리스트도 그대로 반환
        if pd.isna(val) or val == "": return {}
        try:
            return json.loads(val)
        except:
            try:
                return ast.literal_eval(val)
            except:
                return {}

    target_cols = ['productDesc', 'productImage', 'notiItemMap', 'optionItem', 'attributes', 'dispCtgr']
    for col in target_cols:
        if col in df.columns:
            df[col] = df[col].apply(robust_parse)
        else:
            df[col] = [{}] * len(df)

    # ==========================================================
    # [3] 데이터 추출 (여기가 핵심!)
    # ==========================================================
    result = pd.DataFrame()
    
    # 1. 기본 정보
    result['prdNm'] = df['prdNm']
    result['brandNm'] = df['brandMainNmKr']

    # 2. 상세설명 (HTML)
    # 키 이름: prdDescContClob
    result['prdDesc'] = df['productDesc'].apply(lambda x: x.get('prdDescContClob') if isinstance(x, dict) else None)

    # 3. 이미지 URL 
    # 키 이름: basicExtNm (주의: 앞에 도메인이 없을 수 있음)
    result['prdImg'] = df['productImage'].apply(lambda x: x.get('basicExtNm') if isinstance(x, dict) else None)
    
    # 4. 옵션 정보 (리스트 -> 보기 좋은 문자열로 변환)
    # 예: "색상: BLACK, SAND / 사이즈: 95, 100"
    def parse_options(opt_list):
        if not isinstance(opt_list, list): return ""
        summary = []
        for item in opt_list:
            name = item.get('optItemNm', '옵션')
            # 옵션 값들만 추출해서 중복 제거 후 합치기
            values = [v.get('optValueNm') for v in item.get('optValueList', [])]
            unique_vals = sorted(list(set(values))) # 중복제거
            summary.append(f"{name}: {', '.join(unique_vals)}")
        return " / ".join(summary)

    result['options'] = df['optionItem'].apply(parse_options)

    # 5. 상품 고시 정보 (리스트 -> 딕셔너리로 변환)
    # 예: [{'title': '소재', 'value': '면'}] -> {'소재': '면'}
    def parse_notices(noti_list):
        if not isinstance(noti_list, list): return {}
        return {item.get('notiItemTitle'): item.get('notiItemValue') for item in noti_list}

    result['notices'] = df['notiItemMap'].apply(parse_notices)

    # 6. 전시카테고리
    result['category_L'] = df['dispCtgr'].apply(lambda x: x.get('dispCtgrNm1') if isinstance(x, dict) else None)
    result['category_M'] = df['dispCtgr'].apply(lambda x: x.get('dispCtgrNm2') if isinstance(x, dict) else None)
    result['category_S'] = df['dispCtgr'].apply(lambda x: x.get('dispCtgrNm3') if isinstance(x, dict) else None)

    return result

# 추론에 필요한 상품정보 정리
def format_product_metadata(rowData):
    """
    DataFrame의 한 행(row)에서 브랜드, 상품명, 고시정보, 옵션을 추출하여
    AI에게 전달할 텍스트 덩어리로 변환합니다.
    """

    if isinstance(rowData, pd.DataFrame):
        if rowData.empty:
            return "데이터 없음"
        else:
            row = rowData.iloc[0]

    #1. 브랜드 & 상품평
    meta_text = f"[기본 정보]\n"
    meta_text += f"- 브랜드: {row.get('brandNm', '정보없음')}\n"
    meta_text += f"- 상품명: {row.get('prdNm', '정보없음')}\n\n"

    # 2. 정보고시 (notiItemMap) - 리스트 형태 처리
    # 예: [{'notiItemTitle': '소재', 'notiItemValue': '면 100%'}]
    meta_text += f"[정보고시]\n"
    notices = row.get('notices') # 이전 단계에서 notices 컬럼으로 파싱

    if isinstance(notices, dict):
        for key, value in notices.items():
            meta_text += f"- {key}: {value}\n"
    elif isinstance(notices, list):
        for item in notices:
            title = item.get('notiItemTitle', '')
            val = item.get('notiItemValue', '')
            if title:
                meta_text += f"- {title}: {val}\n"
    else:
        meta_text += "(고시정보 없음)\n"
    
    meta_text += "\n"

    # 3. 옵션 정보 (optionItem)
    # 예: [{'optItemNm': '색상', 'optValueList': [...]}]
    meta_text += f"[구매 가능 옵션]\n"
    # 이전 단계에서 만든 'options' 문자열을 그대로 쓰거나, 원본을 다시 파싱
    raw_options = row.get('optionItem')

    if isinstance(raw_options, list):
        for opt in raw_options:
            opt_name = opt.get('optItemNm', '옵션')
            # 옵션 값 리스트 추출
            vals = []
            if 'optValueList' in opt:
                vals = [v.get('optValueNm') for v in opt['optValueList']]
                #중복 제거 및 정렬
                vals = sorted(list(set(vals)))

            val_str = ", ".join(vals)
            meta_text += f"- {opt_name}: {val_str}\n"
    else:
        meta_text += f"{row.get('options', '옵션 정보 없음')}\n"

    return meta_text

# 상품정보 기반 스타일, 속성, 카테고리 등 추론
def analyze_product_with_full_context(html_content, model_name="gpt-4o-mini", base_url=None, max_images=6):
    """
    이미지 + HTML설명 + 메타데이터(브랜드, 스펙, 옵션)를 모두 통합하여 분석
    """
    
    # 1. 메타데이터 텍스트 생성
    metadata_text = format_product_metadata(html_content)
    
    # 2. HTML 상세설명 (기존 로직)
    row = html_content.iloc[0]
    basic_ext_nm = row.get('prdImg', '')
    basic_ext_nm = f"https://cdn2.halfclub.com/rimg/330x440/contain/{basic_ext_nm}?format=webp"
    html_desc = row.get('prdDesc', '')
    if html_desc:
        soup = BeautifulSoup(html_desc, 'html.parser')
        # 텍스트 추출 (구조감을 살리기 위해 줄바꿈 유지)
        clean_desc = soup.get_text(separator="\n", strip=True)[:6000] # 컨텍스트 조금 더 확보
    else:
        clean_desc = "(상세설명 없음)"

    # 3. 프롬프트 구성
    system_prompt = """
    너는 이커머스 상품 분석 전문가다.
    제공된 [이미지]와 [텍스트 정보]를 모두 종합하여 분석하라.
    제공된 텍스트와 상품 이미지를 종합적으로 분석하여 JSON 데이터를 완성하라.

    [중요 지침]
    1. **우선순위**: 이미지와 텍스트 정보가 충돌할 경우, '[기본 정보]', [정보고시], '[구매 가능 옵션]' 텍스트 정보를 진실(Truth)로 간주하라.
    2. 단, 정보고시의 정보가 상품상세참조 같은 불명확한 정보일 경우 정보고시 이외 정보를 진실(Truth)로 간주하라.
    3. 'ai_style'과 'ai_season'은 리스트 형태로 여러 개 선택 가능하다.
    4. 'ai_pit'은 이미지의 착용 샷을 보고 판단하라. (정보가 없으면 '스탠다드'로 추정)
    5. 재질(Material) 정보는 반드시 '[상품 상세 스펙]'에 있는 내용을 바탕으로 작성하라.
    6. 색상 정보는 '[구매 가능 옵션]'에 나열된 정확한 색상명을 포함하라.
    7. description은 이 모든 정보를 종합하여 고객이 신뢰할 수 있는 매력적인 문구로 500자 이내 요약하라.

    [스타일 분류 기준]
    - 미니멀 : 미니멀, 모던, 심플, 깔끔, 군더더기, 절제, 무지, 원톤, 미니멀룩, 클린
    - 클래식 : 클래식, 포멀, 정장, 오피스룩, 출근룩, 하객룩, 격식, 셋업, 수트, 테일러드, 라펠, 싱글/더블, 블레이저, 슬랙스
    - 캐주얼 : 캐주얼, 데일리룩, 이지룩, 편한, 꾸안꾸, 기본템, 일상
    - 페미닌 : 페미닌, 여성스러운, 우아, 분위기, 고급, 단아, 세련
    - 로맨틱 : 로맨틱, 러블리, 사랑스러운, 데이트룩(러블리 문맥), 소녀, 퓨어, 프릴, 레이스, 셔링, 퍼프, 리본, 플라워/잔꽃, 도트
    - 스포티 : 스포티, 애슬레저, 트레이닝, 러닝, 요가, 골프, 테니스, 운동, 기능성, 경량, 방풍, 레깅스, 바람막이, 조거
    - 스트리트 : 스트리트, 힙, 고프코어, 테크웨어, 오버핏, 그래픽, 프린팅, 빅로고, 카고, 워크웨어
    - 휴양지 : 휴양지, 리조트, 바캉스, 여행룩, 썸머룩, 바닷가, 리조트웨어

    [패턴 분류 기준]
    - 무지 : 무지, 솔리드, 원톤, 단색, 민무늬
    - 스트라이프 : 스트라이프, 줄무늬, 줄무니, 세로줄, 가로줄
    - 체크 : 체크
    - 플로럴 : 플로럴, 플로랄, 꽃무늬, 잔꽃
    - 도트 : 도트, 물방울, 물방울무늬
    - 로고/그래픽 : 그래픽
    - 레터링 : 레터링
    - 애니멀 : 애니멀
    - 밀리터리 : 밀리터리
    - 보헤미안/에스닉 : 에스닉
    - 기하학 : 기하학
    - 컬러블록/그라데이션 : 컬러블록
    - 타이다이 : 타이다이
    """

    # 유저 메시지에 메타데이터와 상세설명을 구분해서 주입
    user_content = [
            {
                "type": "text", 
                "text": f"""
                다음은 상품에 대한 텍스트 데이터이다. 이 내용을 분석의 핵심 근거로 삼아라.
                
                {metadata_text}
                
                ----------------
                [상세 페이지 문구]
                {clean_desc}
                """
            }
        ]
    
    if "gemini" in model_name.lower(): 
        user_content = f"""
            다음은 상품에 대한 텍스트 데이터이다. 이 내용을 분석의 핵심 근거로 삼아라.
            
            {metadata_text}
            
            ----------------
            [상세 페이지 문구]
            {clean_desc}
            """
    
    # 이미지 추가 (Base64 변환 로직은 기존과 동일하므로 함수 호출로 대체)
    # --- 2. 스마트 이미지 추출 및 필터링 ---
    found_images = []
    seen_urls = set()
    
    # 모든 img 태그 검색
    for img in soup.find_all('img'):
        src = img.get('src')
        if not src:
            continue
            
        # 절대 경로 변환 (urllib 사용 권장)
        if base_url:
            full_url = urljoin(base_url, src)
        else:
            if src.startswith("//"):
                full_url = "https:" + src
            elif src.startswith("/"):
                # base_url이 없는데 상대 경로면 스킵하거나 로직 추가 필요
                continue 
            else:
                full_url = src

        # [필터링 로직]
        # 1. 중복 제거
        if full_url in seen_urls:
            continue
            
        # 2. 아이콘, 로고, 작은 UI 요소 제외 (파일명이나 클래스명으로 1차 필터)
        lower_src = full_url.lower()
        if any(x in lower_src for x in ['logo', 'icon', 'button', 'tracker', 'pixel', 'sns', 'banner']):
            continue
            
        # 3. (선택사항) 실제 이미지 크기 속성이 있다면 너무 작은 것은 제외
        # width = img.get('width')
        # if width and width.isdigit() and int(width) < 100: continue

        found_images.append(basic_ext_nm)
        found_images.append(full_url)
        seen_urls.add(full_url)
        
        # 최대 개수 도달 시 중단 (비용 관리)
        if len(found_images) >= max_images:
            break

    
    ai_image_inputs = []
    used_image_urls = [] # ★ 실제로 사용된(Base64 변환 성공한) 이미지 URL 저장용

    # 외부 이미지 제한정책으로 인한 로컬 다운로드
    if found_images:
        valid_image_count = 0

        if not "gemini" in model_name.lower(): 
            user_content.append({"type": "text", "text": "상품 이미지들:"})
        
        
        for img_url in found_images:
            # 최대 6장까지만 처리 (비용 및 속도 고려)
            if valid_image_count >= max_images:
                break
                
            # ★ 핵심: URL을 그냥 보내지 않고, Base64로 변환해서 보냄
            base64_image = encode_image_to_base64(img_url)
            
            if base64_image:

                if "gemini" in model_name.lower(): 
                    ai_image_inputs.append(base64_image)
                else:
                    user_content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": base64_image, # 변환된 문자열을 넣음
                            "detail": "low"      # low 모드 유지
                        }
                    })
                    
                used_image_urls.append(base64_image)
                valid_image_count += 1
                print(f"✅ 이미지 변환 성공: {img_url}")
            else:
                print(f"❌ 이미지 변환 실패 (건너뜀): {img_url}")

    # --- 4. OpenAI API 호출 ---
    try:
        response = call_ai_service(
            system_prompt=system_prompt,
            user_text=user_content,
            image_list=ai_image_inputs,
            model_name=model_name
        )

        product_data = response
        return product_data, used_image_urls
        
    except Exception as e:
        print(f"API 호출 중 오류 발생: {e}")
        return None