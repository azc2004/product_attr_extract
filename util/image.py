import requests
import base64
from PIL import Image   # ★ 추가 필요
from io import BytesIO  # ★ 추가 필요


# 외부 사이트 이미지 제한정책으로 인한 이미지 로컬 다운로드 
def encode_image_to_base64(image_url, model_name):
    """
    이미지를 다운로드하여 리사이징 및 압축 후 Base64 리스트로 반환
    - 긴 축 최대 1024px로 리사이징
    - JPEG 품질 70으로 압축
    - 세로로 긴 이미지는 잘라서 처리
    """
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
                if img.mode in ("RGBA", "P"): img = img.convert("RGB") # 포맷 통일

                width, height = img.size                
                # 가로 또는 세로가 50px 미만이면 무시 (아이콘, 추적픽셀 등)
                if width < 50 or height < 50:
                    print(f"🚫 너무 작은 이미지 제외 ({width}x{height}): {image_url}")
                    return None
                
                # 리사이징 설정
                MAX_SIZE = 1024
                JPEG_QUALITY = 85
                results = []

                # gemini 아닌 경우만 해상도 조정
                if not "gemini" in model_name.lower():
                    # img.thumbnail((MAX_SIZE, MAX_SIZE), Image.Resampling.LANCZOS)
                    buf = BytesIO()
                    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
                    b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
                    return f"data:image/jpeg;base64,{b64_str}"

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

# html에서 img 링크 추출
def extract_img_for_html(soup, basic_ext_nm, max_images=6):
    found_images = []
    seen_urls = set()
    
    # 모든 img 태그 검색
    for img in soup.find_all('img'):
        src = img.get('src')
        if not src:
            continue
            
        # 절대 경로 변환 (urllib 사용 권장)
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

        found_images.append(basic_ext_nm)
        found_images.append(full_url)
        seen_urls.add(full_url)
        
        # 최대 개수 도달 시 중단 (비용 관리)
        if len(found_images) >= max_images:
            break
    return found_images