import json
import hashlib
import os
import uuid
from urllib.parse import quote

import streamlit as st

from ai_manager.cli import api_request
from ai_manager.submission_file import MAX_FILE_BYTES, parse_submission_file


def main():
    st.set_page_config(page_title="AI Engineering Manager", layout="wide")
    st.title("AI Engineering Manager")
    st.caption("客户端仅调用后台；关闭页面不会取消任务。仅展示已保存的公开执行证据。")
    base_url = st.sidebar.text_input("API URL", os.environ.get("AIM_API_URL", "http://127.0.0.1:8765"))
    st.session_state.setdefault("submission_key", str(uuid.uuid4()))

    def request(path, payload=None):
        try:
            return api_request(base_url, path, payload)
        except (RuntimeError, ValueError) as exc:
            st.error(str(exc))
            return None


    with st.expander("提交 Feature"):
        uploaded = st.file_uploader("上传 Submission JSON / Markdown", type=["json", "md"])
        if uploaded is not None:
            data = uploaded.getvalue()
            if isinstance(data, bytes):
                try:
                    parsed = parse_submission_file(data, uploaded.name)
                    st.caption(f"最大 {MAX_FILE_BYTES} 字节，UTF-8。文件中的授权不会自动生效。")
                    if parsed.description:
                        st.caption("Markdown 块外文字仅为描述，不作为命令或需求执行。")
                        st.text(parsed.description)
                    digest = hashlib.sha256(data + uploaded.name.encode("utf-8")).hexdigest()
                    if parsed.endpoint == "/workflows":
                        reload_file = st.button("重新填入文件内容")
                        if st.session_state.get("loaded_submission_digest") != digest or reload_file:
                            submission = parsed.submission
                            st.session_state.update({
                                "draft_repo": submission.repo,
                                "draft_base_commit": submission.base_commit,
                                "draft_feature": submission.feature,
                                "draft_allowed": "\n".join(submission.allowed_paths),
                                "draft_tests": "\n".join(submission.test_paths),
                                "draft_acceptance": "\n".join(submission.acceptance),
                                "draft_command": json.dumps(submission.test_command, ensure_ascii=False),
                                "draft_timeout": submission.timeout_seconds,
                                "draft_authorized": False,
                                "draft_key": submission.idempotency_key,
                                "loaded_submission_digest": digest,
                            })
                        st.success("文件已载入下方表单，可修改后点击“提交”；上传本身不会创建后台任务。")
                    else:
                        file_approved = st.checkbox("明确授权上传文件的路径和固定测试命令", value=False,
                                                    key="file_approval_" + digest)
                        file_deploy_approved = False
                        if parsed.endpoint == "/features":
                            file_deploy_approved = st.checkbox("明确授权项目专用本地 SF 部署和 E2E", value=False,
                                                              key="file_deploy_approval_" + digest)
                        if st.button("提交上传文件"):
                            payload = parsed.payload(approved=file_approved)
                            if parsed.endpoint == "/features":
                                payload["deploy_authorized"] = file_deploy_approved
                            result = request(parsed.endpoint, payload)
                            if result is not None:
                                st.session_state["workflow_id"] = result["id"]
                                st.success("提交已保存；未授权任务等待审批。")
                except ValueError as exc:
                    st.error(str(exc))
        with st.form("submit"):
            repo = st.text_input("仓库绝对路径", key="draft_repo")
            base_commit = st.text_input("Base commit", key="draft_base_commit")
            feature = st.text_area("Feature / Manager 需求", key="draft_feature")
            allowed = st.text_area("允许修改路径（每行一个）", key="draft_allowed")
            tests = st.text_area("授权测试路径（每行一个）", key="draft_tests")
            acceptance = st.text_area("验收条件（每行一个）", key="draft_acceptance")
            command = st.text_input("测试命令（JSON 参数数组）",
                                    '["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]', key="draft_command")
            timeout = st.number_input("超时秒数", min_value=10, max_value=3600, value=300, key="draft_timeout")
            authorized = st.checkbox("授权在隔离 worktree 内修改上述范围并执行指定测试", value=False, key="draft_authorized")
            key = st.text_input("提交幂等键（网络失败后保留同一键）", st.session_state.submission_key, key="draft_key")
            submitted = st.form_submit_button("提交")
        if submitted:
            try:
                test_command = json.loads(command)
                if not isinstance(test_command, list) or not all(isinstance(item, str) for item in test_command):
                    raise ValueError("测试命令必须是字符串数组")

                def lines(value):
                    return [line.strip() for line in value.splitlines() if line.strip()]

                result = request("/workflows", {
                    "repo": repo, "base_commit": base_commit, "feature": feature,
                    "allowed_paths": lines(allowed), "test_paths": lines(tests),
                    "acceptance": lines(acceptance), "test_command": test_command,
                    "idempotency_key": key, "authorized": authorized, "timeout_seconds": int(timeout),
                })
                if result is not None:
                    st.session_state["workflow_id"] = result["id"]
                    st.success("提交已保存；未授权任务等待审批。新任务请使用新的幂等键。")
            except ValueError as exc:
                st.error(str(exc))

    with st.expander("四角色自动交付：Manager → Architect → Dev → Tester", expanded=True):
        st.caption("不编写/运行 UT；不启用 Reviewer。须先配置项目、真实 Agent 执行环境与部署/Computer-use bridge。")
        with st.form("delivery_feature"):
            project = st.text_input("已配置项目 ID", "graphconnectors")
            delivery_feature = st.text_area("只告诉 Manager 要实现的 Feature")
            max_rounds = st.number_input("最大自动修复轮数", min_value=0, max_value=20, value=5)
            total_seconds = st.number_input("交付总时限（秒）", min_value=60, max_value=86400, value=7200)
            delivery_key = st.text_input("Feature 幂等键", st.session_state.submission_key, key="delivery_key")
            delivery_authorized = st.checkbox("明确授权项目配置中的源码改动和固定构建", value=False)
            deployment_authorized = st.checkbox("明确授权项目配置中的专用本地 SF 部署和只读数据库/UI 验证", value=False)
            delivery_submitted = st.form_submit_button("交给 Manager 自动交付")
        if delivery_submitted:
            result = request("/features", {"project": project, "feature": delivery_feature,
                "idempotency_key": delivery_key, "authorized": delivery_authorized,
                "deploy_authorized": deployment_authorized, "max_fix_rounds": int(max_rounds),
                "total_timeout_seconds": int(total_seconds)})
            if result is not None:
                st.session_state["workflow_id"] = result["id"]
                st.success("四角色任务已保存；前置能力未验证时将安全阻塞，不会伪报完成。")

    if st.button("刷新后台状态"):
        st.rerun()
    workflows = request("/workflows")
    if workflows is not None:
        st.dataframe(workflows, use_container_width=True)
    workflow_id = st.text_input("Workflow ID（可恢复展示）", key="workflow_id")
    if not workflow_id:
        return
    path = "/workflows/" + quote(workflow_id, safe="")
    detail = request(path)
    if detail is None:
        return
    st.subheader("状态 / 阶段 / Thread IDs / 提交")
    st.json(detail)
    with st.form("input"):
        text = st.text_area("向 Manager 补充需求 / 回答澄清")
        if st.form_submit_button("发送补充") and text.strip():
            if request(path + "/input", {"text": text}) is not None:
                st.rerun()
    approved = st.checkbox("明确授权此任务的已提交路径和命令", value=False)
    if st.button("批准", disabled=not approved):
        if request(path + "/approve", {"approved": True}) is not None:
            st.rerun()
    if st.button("显式重试"):
        if request(path + "/retry", {}) is not None:
            st.rerun()
    if st.button("取消任务"):
        if request(path + "/cancel", {}) is not None:
            st.rerun()
    st.subheader("实际事件 / 对话 / 命令")
    events = request(path + "/events")
    if events is not None:
        st.json(events)
    st.subheader("产物 / Diff / 日志 / 报告")
    artifacts = request(path + "/artifacts")
    if artifacts is not None:
        st.json(artifacts)
        for artifact in artifacts:
            name = artifact.get("name")
            if name:
                st.link_button(name, base_url.rstrip("/") + path + "/artifacts/" + quote(name, safe=""))


if __name__ == "__main__":
    main()
