import streamlit as st


def model_settings(request):
    with st.expander("模型与账号：Codex SDK / GitHub Copilot", expanded=True):
        st.caption("模型连接与源码执行能力分开验证。连接成功不会解除执行隔离阻塞；此处不收集或显示密钥。")
        if st.button("检查账号与后端状态"):
            result = request("/models/providers")
            if result is not None:
                st.session_state["model_provider_status"] = result
                st.success("状态已刷新；此检查不会调用模型。")
            else:
                st.error("无法获取状态，请检查后台与 Adapter 是否启动。")
        if "model_provider_status" in st.session_state:
            for item in st.session_state["model_provider_status"].get("providers", []):
                account = {True: "已登录", False: "未登录或检测失败", None: "未验证（需真实连接测试）"}.get(item.get("authenticated"))
                st.write(f"**{item.get('id')}** · CLI：{'已发现' if item.get('installed') else '未发现'} · 认证：{account}")
                if not item.get("execution_ready"):
                    st.warning("自动开发执行未就绪：" + str(item.get("blocker", "unknown")))
            with st.expander("原始状态详情"):
                st.json(st.session_state["model_provider_status"])
        st.caption("检查按钮仅检测 CLI、登录状态与执行能力，不会登录账号或验证模型响应。Codex 使用后台进程的本机认证环境；此页不读取或展示账号邮箱。")
        st.code("codex login\ncopilot login", language="powershell")
        st.caption("在本机终端按所选后端登录。Copilot 使用 GitHub/Copilot 权益；GitHub 登录不等于 Codex 认证。后台须使用同一 Windows 用户与认证环境。")

        def choose(label, key):
            provider = st.selectbox(label + " 后端", ["codex", "copilot"], key=key + "_provider")
            if st.button(label + " 获取模型目录", key=key + "_catalog"):
                catalog = request("/models/catalog", {"provider": provider})
                if catalog is not None:
                    st.session_state["catalog_" + provider] = catalog
            catalog = st.session_state.get("catalog_" + provider, {})
            models = [item["id"] for item in catalog.get("models", []) if item.get("id")]
            chosen = st.selectbox(label + " 目录模型", ["使用默认/手动输入"] + models, key=key + "_" + provider + "_model")
            model = chosen if chosen != "使用默认/手动输入" else st.text_input(label + " 模型 ID（空值使用后端默认）", value="gpt-6.1-sol" if provider == "codex" else "auto", key=key + "_" + provider + "_custom").strip()
            selection = {"provider": provider}
            if model:
                selection["model"] = model
            if provider == "codex":
                entry = next((item for item in catalog.get("models", []) if item.get("id") == model), {})
                levels = entry.get("efforts") or ["minimal", "low", "medium", "high", "xhigh", "max", "ultra", "persistent"]
                effort_options = ["后端默认"] + levels
                effort = st.selectbox(label + " 推理强度", effort_options, index=effort_options.index("low") if "low" in effort_options else 0, key=key + "_effort")
                if effort != "后端默认":
                    selection["effort"] = effort
            else:
                st.caption("Copilot ACP 推理强度设置尚未验证，不发送该参数；所有工具权限默认拒绝。")
            if catalog:
                st.caption("目录来源：" + catalog.get("source", "unknown") + "；目录存在不代表模型访问或执行权限已验证。")
            return selection

        default = choose("默认", "agent_default")
        role_models = {}
        enabled = st.checkbox("将模型选择写入新任务", value=False, key="agent_model_enabled")
        if enabled:
            for role in ("manager", "architect", "dev", "test", "reviewer"):
                role_models[role] = dict(default)
            with st.expander("按角色覆盖模型"):
                for role in role_models:
                    if st.checkbox(role + " 单独配置", key="agent_override_" + role):
                        role_models[role] = choose(role, "agent_" + role)
            st.json(role_models)

        approved = st.checkbox("批准一次真实连接验证（可能产生模型用量；仅发送固定诊断，不执行 Feature）", value=False)
        if st.button("验证默认模型真实调用", disabled=not approved):
            result = request("/models/probes", default | {"approved": approved})
            if result is not None:
                st.session_state["model_probe_id"] = result["id"]
        if st.session_state.get("model_probe_id"):
            st.button("刷新模型调用结果")
            result = request("/models/probes/" + st.session_state["model_probe_id"])
            if result is not None:
                st.json(result)
        return role_models
