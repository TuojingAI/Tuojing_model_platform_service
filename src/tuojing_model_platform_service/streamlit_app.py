from __future__ import annotations

import os

import httpx
import streamlit as st


API_URL = os.environ.get("MODEL_PLATFORM_API_URL", "http://127.0.0.1:8000").rstrip("/")
TIMEOUT_SECONDS = 300.0


def post(path: str, payload: dict) -> dict:
    try:
        response = httpx.post(
            f"{API_URL}{path}", json=payload, timeout=TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as error:
        try:
            body = error.response.json()
            detail = body.get("detail", error.response.text)
            suggested_command = body.get("suggested_command")
            if suggested_command:
                detail = f"{detail}\n\n建议由目录所有者执行：\n{suggested_command}"
        except ValueError:
            detail = error.response.text
        raise RuntimeError(detail) from error
    except httpx.HTTPError as error:
        raise RuntimeError(f"cannot connect to API: {error}") from error


st.set_page_config(page_title="Tuojing Model Platform", layout="wide")
st.title("Tuojing Model Platform")
st.caption(f"API: {API_URL}")

release_tab, query_tab = st.tabs(["新增模型", "查询模型"])

with release_tab:
    with st.form("release-model"):
        project_name = st.text_input("项目名称")
        model_name = st.text_input("模型名称")
        source_path = st.text_input(
            "模型目录", placeholder="/home/user/projects/umi-policy/"
        )
        released_by = st.text_input("发布人（可选）")
        version_strategy = st.selectbox(
            "版本策略",
            options=["patch", "minor", "major", "exact"],
            format_func={
                "patch": "默认：补丁版本 +1",
                "minor": "中版本 +1",
                "major": "大版本 +1",
                "exact": "指定版本",
            }.get,
        )
        version = st.text_input(
            "指定版本",
            placeholder="1.2.3",
            disabled=version_strategy != "exact",
        )
        force_replace = st.checkbox("覆盖已经存在的版本")
        submitted = st.form_submit_button("发布模型", type="primary")

    if submitted:
        payload = {
            "project_name": project_name.strip(),
            "model_name": model_name.strip(),
            "source_path": source_path.strip(),
            "released_by": released_by.strip() or None,
            "version_strategy": version_strategy,
            "force_replace": force_replace,
        }
        if version_strategy == "exact":
            payload["version"] = version.strip()
        try:
            result = post("/api/v1/models/release", payload)["model"]
            st.success(f"模型发布成功：{result['version']}")
            st.json(result)
        except RuntimeError as error:
            st.error(str(error))

with query_tab:
    with st.form("query-models"):
        query_project = st.text_input("项目名称", key="query-project")
        query_model = st.text_input("模型名称", key="query-model")
        query_version = st.text_input("版本", key="query-version")
        latest_only = st.checkbox("只看最新版本", value=True)
        queried = st.form_submit_button("查询", type="primary")

    if queried:
        payload = {
            "project_name": query_project.strip() or None,
            "model_name": query_model.strip() or None,
            "version": query_version.strip() or None,
            "latest_only": latest_only,
        }
        try:
            models = post("/api/v1/models/query", payload)["models"]
            st.write(f"共 {len(models)} 条结果")
            st.dataframe(models, use_container_width=True, hide_index=True)
        except RuntimeError as error:
            st.error(str(error))
