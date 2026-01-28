from schema.product import ProductSchema # 사용자가 정의한 스키마

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