import os
import json
import base64
import streamlit as st
import google.generativeai as genai  # Gemini용 SDK
from openai import OpenAI
from urllib.parse import urljoin
from schema.product import ProductSchema # 사용자가 정의한 스키마


# ==========================================
# [1] AI 통신 전담 함수 (핵심 변경 부분)
# ==========================================
def call_ai_service(system_prompt, user_text, image_list, model_name):
    """
    모델 이름에 따라 적절한 AI 서비스를 호출하고, 결과를 ProductSchema 형태로 반환합니다.
    """
    
    # 1. Google Gemini (Flash, Pro 등)
    if "gemini" in model_name.lower():
        return _call_gemini_api(system_prompt, user_text, image_list, model_name)
    
    # 2. Qwen (OpenAI 호환 API 사용 권장) 또는 기타 OpenAI 호환 모델
    elif "qwen" in model_name.lower():
        # Qwen용 클라이언트가 별도로 없으면 기존 client 사용하거나 새로 생성
        client = OpenAI(base_url=st.secrets["DASHSCOPE_API_URL"], api_key=st.secrets["DASHSCOPE_API_KEY"])
        return _call_openai_compatible(system_prompt, user_text, image_list, model_name, client)

    # 3. 기본 OpenAI (GPT-4o 등)
    else:
        # ★ [수정] Client가 없으면 api_key로 생성하는 로직 추가
        client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
        return _call_openai_native(system_prompt, user_text, image_list, model_name, client)

# --- [내부 함수 1] Google Gemini 호출 로직 ---
def _call_gemini_api(system_prompt, user_text, image_list, model_name):
    try:
        # API 키 설정 (환경변수나 별도 설정 파일에서 가져오는 것을 권장)
        # st.secrets["GOOGLE_API_KEY"] 등을 사용할 수 있습니다.
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"]) 
        
        # Generation Config (JSON 응답 강제)
        generation_config = {
            "temperature": 0.2,
            "response_mime_type": "application/json",
            "response_schema": ProductSchema # Pydantic 모델 직접 지원
        }

        model = genai.GenerativeModel(
            model_name=model_name, # 예: "gemini-2.5-flash"
            system_instruction=system_prompt,
            generation_config=generation_config
        )

        # Gemini는 리스트 안에 텍스트와 이미지(Blob)를 섞어서 전달
        content_parts = [user_text]
        
        for img_data in image_list:
            # Base64 문자열에서 헤더 제거하고 Bytes로 변환
            # 예: "data:image/jpeg;base64,AAAA..." -> b'AAAA...'
            if isinstance(img_data, str) and "base64," in img_data:
                header, encoded = img_data.split("base64,", 1)
                mime_type = header.split(":")[1].split(";")[0] # image/jpeg
                img_bytes = base64.b64decode(encoded)
                
                content_parts.append({
                    "mime_type": mime_type,
                    "data": img_bytes
                })

        response = model.generate_content(content_parts)
        
        # JSON 문자열을 Pydantic 객체로 변환
        # Gemini SDK의 response.text는 JSON 문자열임
        json_result = json.loads(response.text)
        return ProductSchema(**json_result)

    except Exception as e:
        print(f"Gemini 호출 오류: {e}")
        return None

# --- [내부 함수 2] OpenAI Native 호출 로직 (Structured Output 사용) ---
def _call_openai_native(system_prompt, user_text, image_list, model_name, client):
    try:
        response = client.beta.chat.completions.parse(
            model=model_name, 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            response_format=ProductSchema, # 사용자가 정의한 Pydantic 모델
            temperature=0.2
        )
        
        product_data = response.choices[0].message.parsed

        return product_data
            
    except Exception as e:
        # ★ [수정] 화면에 에러 출력
        st.error(f"❌ OpenAI(GPT) 호출 오류 상세: {str(e)}")
        return None

# --- [내부 함수 3] Qwen 등 호환 API 호출 로직 ---
def _call_openai_compatible(system_prompt, user_text, image_list, model_name, client):
    """
    Qwen 등은 OpenAI 호환 API를 제공하지만, 'beta.parse' (Structured Output)를 
    지원하지 않는 경우가 많으므로 일반적인 JSON Mode로 처리합니다.
    """
    try:
        response = client.beta.chat.completions.parse(
            model=model_name, 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text}
            ],
            response_format=ProductSchema, # 사용자가 정의한 Pydantic 모델
            temperature=0.2
        )
        
        product_data = response.choices[0].message.parsed

        return product_data
        
    except Exception as e:
        # [핵심] Qwen 에러 상세 출력
        st.error(f"❌ Qwen(DashScope) API 에러 상세: {str(e)}")
        
        # 이미지가 너무 커서 나는 에러인지 확인하기 위해 payload 길이 출력해보기
        if len(image_list) > 0:
            st.warning(f"전송 시도한 이미지 개수: {len(image_list)}")
        
        return None