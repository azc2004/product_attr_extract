import openai
import argparse
import pandas as pd
import streamlit as st
import json
from util.product import getProductInfo, analyze_product_with_full_context
from util.search import getPrdListByKeyword, process_es_hit_to_display

# parser = argparse.ArgumentParser(
#     description="LLM"
# )
# parser.add_argument('prdNo', type=str)
# args = parser.parse_args()
# prdNo = args.prdNo

# # --- 설정 ---
# # 실제 운영 시에는 환경 변수 등으로 관리하세요.
OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# # 실행
# json_result = getProductInfo(prdNo)
# result = analyze_product_with_full_context(json_result, client=client)
# print(result)

# ==========================================
# Streamlit UI 메인
# ==========================================
def main():
    st.set_page_config(page_title="AI 상품 분석기")
    
    st.markdown("""
    <style>
    /* 카드 스타일 미세 조정 */
    .stButton > button {
        width: 100%;
    }
    img {
        border-radius: 8px;
    }
    </style>
    """, unsafe_allow_html=True)

    st.title("🛍️ 이커머스 상품 정보 AI 분석기")
    
    if "search_results" not in st.session_state: st.session_state.search_results = []
    if "selected_product" not in st.session_state: st.session_state.selected_product = None
    if "ai_result" not in st.session_state: st.session_state.ai_result = None

    # ----------------------------------------------
    # Step 1: 검색 (Mock Data for ES)
    # ----------------------------------------------
    st.subheader("1. 상품 검색")
    with st.form(key="search_form"):
        col1, col2 = st.columns([4, 1], vertical_alignment="bottom")
        with col1:
            search_query = st.text_input("검색어 입력", "원피스")
        with col2:
            search_btn = st.form_submit_button("검색", type="primary", width="stretch")

    if search_btn:
        # ---------------------------------------------------------
        # [MOCK DATA] 실제 ES 응답 구조 흉내 (스크린샷 기반)
        # ---------------------------------------------------------
        es_response = getPrdListByKeyword(1, search_query)
        
        # 실제 데이터 바인딩
        hits = es_response['data']['result']['hits']['hits']
        st.session_state.search_results = [process_es_hit_to_display(hit) for hit in hits]
        st.session_state.selected_product = None
        st.session_state.ai_result = None

    # ----------------------------------------------
    # Step 2: 리스트 출력 (5개씩 그리드 + 선택 버튼)
    # ----------------------------------------------
    search_results = st.session_state.search_results

    # [설정] 세션 상태 초기화 (모델 정보 저장용)
    if "is_analyzing" not in st.session_state: st.session_state.is_analyzing = False
    if "analyzing_product_name" not in st.session_state: st.session_state.analyzing_product_name = ""
    if "current_model" not in st.session_state: st.session_state.current_model = "GPT-4o" # 기본값

    if search_results:
        st.divider()
        st.subheader(f"2. 검색 결과 ({len(search_results)}건)")
        
        # 5개씩 끊어서 행 만들기
        cols_per_row = 5
        for i in range(0, len(search_results), cols_per_row):
            cols = st.columns(cols_per_row)
            
            # 각 Row 안에서 Column 채우기
            for j in range(cols_per_row):
                if i + j < len(search_results):
                    item = search_results[i + j]
                    with cols[j]:
                        # 이미지 링크 처리 (기존 유지)
                        if item['img_url']:
                            link_url = f"https://www.halfclub.com/product/{item['prdNo']}"
                            st.markdown(
                                f"""<a href="{link_url}" target="_blank"><img src="{item['img_url']}" style="width:100%; border-radius:8px; cursor:pointer;"></a>""",
                                unsafe_allow_html=True
                            )
                        else:
                            st.write("No Image")
                        
                        # 상품 정보 (브랜드/상품명)
                        st.caption(item['brand'])
                        # 상품명이 너무 길면 ... 처리 (UI 깨짐 방지)
                        short_name = (item['name'][:20] + '..') if len(item['name']) > 20 else item['name']
                        st.text(short_name)
                        
                        # [핵심 변경] 버튼 2개 분리 (gpt-4o / gpt-4o-mini)
                        col_btn1, col_btn2 = st.columns(2)
                        
                        with col_btn1:
                            btn_4o = st.button("4o", key=f"btn_4o_{item['prdNo']}", type="primary", use_container_width=True)
                        with col_btn2:
                            btn_mini = st.button("mini", key=f"btn_mini_{item['prdNo']}", use_container_width=True)

                        # 어떤 버튼이 눌렸는지 확인 및 모델 설정
                        selected_model = None
                        if btn_4o:
                            selected_model = "gpt-4o"
                        elif btn_mini:
                            selected_model = "gpt-4o-mini"

                        # 버튼 클릭 로직 실행
                        if selected_model:
                            # 1. 데이터 준비
                            processed_df = getProductInfo(item['prdNo'])
                            row = processed_df

                            st.session_state.selected_product = row

                            # [핵심] 선택한 모델명과 분석 상태 저장
                            st.session_state.current_model = selected_model
                            st.session_state.analyzing_product_name = item['name']
                            st.session_state.is_analyzing = True
                            
                            # 3. 화면 갱신
                            st.rerun()
        
        # ----------------------------------------------
        # [중간] 분석 로딩 및 실행 영역
        # ----------------------------------------------
        if st.session_state.is_analyzing and st.session_state.selected_product is not None:
            st.divider()
            target_name = st.session_state.analyzing_product_name
            model_name = st.session_state.current_model # 저장된 모델명 가져오기
            
            error_placeholder = st.empty()
            
            # 스피너 문구에도 모델명 표시
            with st.spinner(f"🤖 AI({model_name})가 '{target_name}' 상품을 정밀 분석 중입니다..."):
                try:
                    row = st.session_state.selected_product
                    
                    # 선택된 모델로 분석 실행
                    result = analyze_product_with_full_context(
                        row, 
                        client=client, 
                        model_name=model_name
                    )
                    st.session_state.ai_result = result
                except Exception as e:
                    st.session_state.ai_result = None
                    error_placeholder.error(f"❌ 분석 중 오류가 발생했습니다: {e}")
                finally:
                    st.session_state.is_analyzing = False
                    # 자연스럽게 아래 Step 3로 진행

    # ----------------------------------------------
    # Step 3: 상세 정보 및 분석 결과
    # ----------------------------------------------
    if st.session_state.selected_product is not None:
        row = st.session_state.selected_product
        
        st.divider()
        st.subheader("3. 상품 분석 결과")
        
        # [상단 레이아웃] 좌: 이미지 / 우: 텍스트 정보 + 디버그
        c_left, c_right = st.columns([1, 1], gap="large")
        
        # === 왼쪽 컬럼: 상품 이미지 ===
        with c_left:
            st.markdown("#### 🖼️ 상품 이미지")
            if row.iloc[0]['prdImg']:
                try:
                    img_url = row.iloc[0]['prdImg']
                    if not img_url.startswith("http"):
                         img_url = f"https://cdn2.halfclub.com/{img_url.lstrip('/')}"
                    st.image(img_url, caption="상세 이미지", width="stretch")
                except:
                    st.error("이미지 로드 실패")
            else:
                 st.write("이미지 없음")

        # === 오른쪽 컬럼: 텍스트 정보 + 디버그 정보 ===
        with c_right:
            # 1. 텍스트 정보
            st.markdown("#### 📝 상품 정보")
            st.markdown(f"**상품명:** {row.iloc[0]['prdNm']}")
            st.markdown(f"**브랜드:** {row.iloc[0]['brandNm']}")
            opt_txt = row.iloc[0]['options'] if row.iloc[0]['options'] != "옵션 정보 없음" else "정보 없음 (ES 데이터)"
            st.markdown(f"**옵션:** {opt_txt}")
            
            # 2. 디버그 정보 (접이식)
            st.write("") 
            with st.expander("🔍 분석용 데이터 원본 (JSON Code)"):
                try:
                    debug_data = row.iloc[0].to_dict()
                    json_str = json.dumps(debug_data, indent=2, ensure_ascii=False)
                    st.code(json_str, language="json")
                except:
                    st.write("데이터 변환 오류")
        
        # ---------------------------------------------------------
        # [하단 레이아웃] AI 분석 리포트 (컬럼 밖으로 이동 -> 전체 너비 사용)
        # ---------------------------------------------------------
        st.divider()

        # [핵심 변경] 사용된 모델명을 타이틀에 표시
        used_model = st.session_state.get('current_model', 'Unknown')
        st.markdown(f"#### 🤖 AI 분석 리포트 (Model: `{used_model}`)")
        
        if st.session_state.ai_result:
            res = st.session_state.ai_result
            
            # 탭으로 결과 보여주기
            tab1, tab2 = st.tabs(["📋 스펙 분석", "✍️ 마케팅 카피"])
            
            with tab1:
                st.success(f"AI({used_model})가 분석한 스타일 및 속성입니다.")
                try:
                    # 카테고리 등 속성 정보 그리드 배치
                    col_a, col_b, col_c = st.columns(3)
                    with col_a:
                        # 구조가 버전에 따라 다를 수 있어 안전하게 처리
                        try:
                            st.write(f"**카테고리:**\n{res.ai_category_L} > {res.ai_category_M} > {res.ai_category_S}")
                        except:
                            st.write(f"**카테고리:**\n{getattr(res, 'ai_category_L', '')} > {getattr(res, 'ai_category_M', '')} > {getattr(res, 'ai_category_S', '')}")
                        st.write(f"**성별:**\n{res.ai_gender}")
                    
                    with col_b:
                        st.write(f"**계절:**\n{', '.join(res.ai_season)}")
                        st.write(f"**스타일:**\n{', '.join(res.ai_style)}")
                    
                    with col_c:
                        st.write(f"**핏:**\n{res.ai_pit}")
                        st.write(f"**패턴:**\n{res.ai_pattern}")
                except:
                    st.error("결과 표시 중 오류가 발생했습니다.")
            
            with tab2:
                st.info(f"{used_model} 모델이 작성한 상품 소개 문구입니다.")
                st.markdown(f"> {res.description}")
        else:
            # 아직 분석 결과가 없을 때
            st.info("분석된 결과가 없습니다. 다시 시도해주세요.")

if __name__ == "__main__":
    main()