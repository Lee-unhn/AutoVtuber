"""PersonaGenerator — 把使用者表單轉成 VTuber 人設 markdown（透過 Ollama）。

職責：
    1. 重用 PromptBuilder.warmed_session() 共享 Ollama 載入（不 double-warm）
    2. 與 SDXL prompt 在同一個 acquire 內生成 persona
    3. 失敗 fallback：純規則組裝的中文 persona 模板（pipeline 永遠繼續）
    4. 寫檔到 output/<basename>_persona.md

設計基於 AUTOVTUBER.md「Persona Generator 模組規格」章節。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import requests

from ..utils.logging_setup import get_logger
from .job_spec import FormInput, Personality, StyleGenre

_log = get_logger(__name__)


@dataclass
class OllamaSession:
    """共享 Ollama 連線資訊（由 PromptBuilder.warmed_session() 提供）。"""

    base_url: str
    model: str
    session: requests.Session
    timeout_seconds: int


_SYSTEM_PROMPT = """你是專業的 VTuber 人格設定師。請根據使用者提供的角色屬性表單，
生成一份完整、生動、可直接使用的中文 VTuber 人設文件。

輸出格式：嚴格 markdown，必須包含以下七個章節，章節標題用 `## ` 開頭：

## 基本資料
- 名字：（與使用者提供的 nickname 一致；可加同音英文名作為直播代號）
- 年齡：（VTuber 通常 16-25，根據個性與風格選擇）
- 身高：（135-175 cm 之間）
- 生日：（月/日，符合星座個性）

## 個性詳細
條列 5-10 條描述，包括優點、小缺點、情緒反應模式、面對挑戰的態度。

## 背景故事
一段 400-600 字的中文敘述，包含：出身設定（普通人類 / 異世界 / 賽博 / 奇幻 種族）、
為何成為 VTuber、生活中的轉折點、目前處境、夢想或目標。
故事必須與「外觀屬性」「個性」「風格」彼此自洽。

## 興趣與嗜好
條列 5 條，符合個性與背景。

## 口頭禪
條列 3-5 個短句（中文），是這位 VTuber 開直播或受到刺激時會脫口而出的話。

## 直播風格建議
描述適合的內容類型（雜談 / 遊戲種類 / ASMR / 歌回 / 創作回 / 學習回 等），
解釋為什麼適合，並給出 2-3 個具體的「節目企劃」點子。

## 與觀眾互動方式
描述如何稱呼粉絲、互動的語氣、是否有特別的應援方式、收到 SC 的反應習慣等。

規則：
- 全部用繁體中文
- 不可加上「以下是您的 VTuber 設定」之類的開場白與結語
- 不可加 ``` markdown 圍欄
- 直接輸出 `## 基本資料` 開頭

**反套路規則（重要 — 角色辨識度差別在這）：**
背景故事與口頭禪「禁止」純粹使用以下泛用模板，除非搭配具體、可被「持物 / 場景 / 事件」
辨識的獨特元素：
- 「神秘過去 / 不願多談」  →  必須改成有「具體一件物品」象徵（如「總帶著一支壞掉的老錶」）
- 「賽博城市夜行者 / 逃離監控」  →  必須加可視化裝備或場景（如「腰間掛著舊式底片相機」）
- 「害羞但偶爾很可靠」  →  必須有具體切換時機（如「聽到觀眾彈幕喊『加油』時 200% 變身」）
- 「對自己的能力很有信心」  →  必須有可笑的弱點（如「方向感極差連 7-11 都會迷路」）
- 「異世界轉生」  →  必須說明「為何選擇 VTuber 而不是其他職業」並給具體理由

角色的「**簽名 prop / 簽名動作 / 簽名梗**」是辨識度的關鍵。**至少**在「背景故事」或
「口頭禪」加 1 個具體可被觀眾複述的元素（如：固定戴的耳機 / 開直播第一句的打招呼動作 /
固定的小道具）。
"""


# ---------------- Templated fallback（不需 LLM 也能跑） ---------------- #

_PERSONALITY_DESCRIPTIONS: dict[Personality, list[str]] = {
    Personality.CHEERFUL_OUTGOING: [
        "笑容是天然的能量燈泡，走到哪亮到哪",
        "面對陌生人也能 30 秒內找到話題",
        "情緒外顯，難過也藏不住",
        "喜歡熱鬧場合，獨處久了會無聊",
        "願意主動讓場子熱起來",
    ],
    Personality.CALM_INTROVERTED: [
        "說話節奏穩定，不太被外界帶亂",
        "更喜歡深度對話而非閒聊",
        "獨處時能完整充電",
        "面對突發狀況會先冷靜分析",
        "有點完美主義但能控制比例",
    ],
    Personality.SHY_GENTLE: [
        "說話聲音偏小但溫柔",
        "被誇獎會臉紅",
        "很在意別人感受",
        "面對衝突會想先逃避再思考",
        "對熟人才會打開話匣子",
    ],
    Personality.CONFIDENT_LEADER: [
        "天生有指揮場面的氣場",
        "果斷做決定不糾結",
        "對自己選擇的事有強烈責任感",
        "有時會忽略隊友情緒",
        "目標導向，討厭浪費時間",
    ],
    Personality.PLAYFUL_TEASING: [
        "開玩笑是表達親近的方式",
        "腦中常有奇怪冷笑話倉庫",
        "看到正經人會忍不住戳一下",
        "其實很觀察對方底線",
        "情緒高昂時話會變多",
    ],
    Personality.CARING_NURTURING: [
        "天生會照顧人，連寵物都會自動湊過來",
        "記得每個朋友的喜好",
        "對方一個小情緒變化就察覺",
        "有時太想幫忙會把自己累壞",
        "煮飯/打掃/收納樣樣行",
    ],
    Personality.MYSTERIOUS_COOL: [
        "話不多，每句都讓人想多想兩秒",
        "對自己過去保留一份神秘",
        "情緒表達極簡但不冷漠",
        "對音樂/書籍/電影品味獨特",
        "需要時又能瞬間切換成可靠的人",
    ],
    Personality.ENERGETIC_CHAOTIC: [
        "腦中同時開 8 個分頁",
        "話題跳躍但跟得上的人會很快樂",
        "對新東西好奇心爆表",
        "需要被提醒才會吃飯",
        "情緒像煙火，亮但快收",
    ],
    Personality.SERIOUS_FOCUSED: [
        "進入工作模式眼神會變",
        "不喜歡被打斷",
        "對細節要求高",
        "私下其實有反差萌",
        "守時，遲到會自責一整天",
    ],
    Personality.DREAMY_ARTISTIC: [
        "腦中常有畫面與音樂在跑",
        "靈感來時會忘記時間",
        "對顏色與光影特別敏感",
        "說話帶詩意",
        "情緒起伏受作品影響大",
    ],
    Personality.ANALYTICAL_LOGICAL: [
        "看事情先拆結構",
        "喜歡資料與圖表",
        "面對情緒問題會想先理性分析",
        "有時太重邏輯被說冷",
        "很享受 debug 與解謎",
    ],
    Personality.ADVENTUROUS_BRAVE: [
        "新景點、新食物、新遊戲都先衝再說",
        "高度耐挫，跌倒立刻爬起",
        "膽子大但不魯莽",
        "對未知有強烈渴望",
        "故事多到能講三天",
    ],
    Personality.KIND_HARMONIOUS: [
        "團體裡的潤滑劑",
        "傾向尋找雙贏方案",
        "對他人苦難有同理心",
        "不喜歡為小事爭執",
        "願意為朋友付出時間",
    ],
    Personality.PROUD_NOBLE: [
        "對自己標準很高",
        "舉止優雅，有禮儀感",
        "不輕易示弱",
        "重視承諾與名譽",
        "私底下其實會在意小事",
    ],
    Personality.CURIOUS_CHILDLIKE: [
        "對什麼都想問為什麼",
        "看到漂亮東西眼睛會發光",
        "不會把自己看得很重",
        "情緒直接，開心就笑、不爽就皺眉",
        "喜歡蒐集小東西",
    ],
    Personality.QUIET_OBSERVANT: [
        "話少但每句都觀察過",
        "團體裡常被低估",
        "需要時又能精準說出關鍵",
        "獨立性強",
        "對環境變化敏感",
    ],
}

# 反套路：每個 style 有具體的「身份 / 場景 / 信念」，禁用泛用詞
# （賽博/逃離/監控/神秘過去/異世界/轉生）
_STYLE_BACKGROUND: dict[StyleGenre, str] = {
    StyleGenre.ANIME_MODERN: "二手書店打工的大三學生，因為意外整理出一本沒有作者名的日記而開始記錄自己的故事",
    StyleGenre.ANIME_CLASSIC: "祖母留下一台 1995 年的卡式錄音機，現在用它錄製直播的開場白與結尾",
    StyleGenre.CHIBI: "小學三年級的妹妹偷偷幫忙設計造型，每天直播前要先回答妹妹一個問題才能開台",
    StyleGenre.CYBERPUNK: "白天在霓虹招牌維修店學徒，撿到一個壞掉的耳機，修好後發現裡面留著前主人錄好的 47 段語音",
    StyleGenre.COTTAGECORE: "經營一座只賣三種口味果醬的小店，店裡的木椅是奶奶留下的，每天直播前會擦一遍",
    StyleGenre.SEMI_REALISTIC: "保險業務員轉行做插畫家，第一份作品是把自家貓畫成警察主題的圖鑑",
}


# 反套路：每個 style 給一個 concrete signature prop（可被觀眾複述 / 製作粉絲商品）
_STYLE_SIGNATURE_PROP: dict[StyleGenre, str] = {
    StyleGenre.ANIME_MODERN: "舊書店帶回來的木質書籤（兩面寫不同字句）",
    StyleGenre.ANIME_CLASSIC: "祖母留下的卡式錄音機（隨身攜帶，會在開播時按下 REC 按鈕）",
    StyleGenre.CHIBI: "妹妹手作的毛線吊飾（每集顏色都不同）",
    StyleGenre.CYBERPUNK: "撿到的舊耳機（左耳邊有個被刮掉的貼紙痕跡，露出原本的圖樣一角）",
    StyleGenre.COTTAGECORE: "繡了三朵小花的圍裙（直播時穿，洗了會褪色變淡）",
    StyleGenre.SEMI_REALISTIC: "藏在筆筒最底下的便條紙（寫滿 38 個自我吐槽，會偶爾抽一張念）",
}


# 反套路 regex：偵測到這些字串視為「套路汙染」，要走 safe 替代
_BANNED_TROPE_PATTERNS = (
    "賽博城市",
    "逃離現實",
    "逃離現實的監控",
    "用 VTuber 身分逃離",
    "cyberpunk",
    "Cyberpunk",
    "異世界轉生",
    "從小就對「被看見」這件事有複雜情感",  # 模板舊段落，已淘汰
    "用另一個外型表達真實的自己",
)


def _contains_banned_trope(text: str) -> str | None:
    """掃描文字找第一個 banned trope；找到回傳該字串，沒找到回 None。"""
    for pat in _BANNED_TROPE_PATTERNS:
        if pat in text:
            return pat
    return None


def _template_persona(form: FormInput) -> str:
    """純規則 fallback persona — Ollama 不可用時保證 pipeline 不斷掉。

    反套路：每個 style 有具體的物件 / 事件，禁止用 cyberpunk / 異世界轉生 / 逃離監控 等泛詞。
    一定包含「簽名 prop」段落讓觀眾有可複述的記憶點。
    """
    desc_list = _PERSONALITY_DESCRIPTIONS.get(form.personality, [])
    desc_lines = "\n".join(f"- {d}" for d in desc_list) or "- 個性溫和，待人和善"
    bg_setting = _STYLE_BACKGROUND.get(form.style, "在某個小城裡靜靜過著日常的人")
    signature_prop = _STYLE_SIGNATURE_PROP.get(form.style, "一個被使用很久、邊角磨白的小物件")
    nick = form.nickname or "無名"

    return f"""## 基本資料
- 名字：{nick}
- 年齡：18
- 身高：158 cm
- 生日：4/15

## 個性詳細
{desc_lines}

## 簽名 Prop
{signature_prop} — 每場直播都會出現，是觀眾辨認 {nick} 的關鍵記憶點。

## 背景故事
{nick} 是{bg_setting}。某天朋友隨口說了一句「你講話的方式有點像在錄音」，那句話像是
打開了一個按鈕——{nick} 才意識到自己其實一直在替別人留下什麼，只是沒被注意過。
從那之後 {nick} 開始把日常的小發現、誤打誤撞的失敗、和對某些事情無法解釋的執著
拍下來、講出來、整理成直播。觀眾不是來看完整故事的人，是來陪 {nick} 把片段慢慢拼起來的。
直播間漸漸成為一個交換片段的角落，{nick} 在這裡學會接住觀眾，也被觀眾接住。
目標不是變成大型 VTuber，是希望某一天能在線下見到那群「也願意慢下來的人」並擁抱他們。

## 興趣與嗜好
- 收集老物件並記錄它們的「上一手故事」
- 看電影並寫長篇心得（特別偏愛被低估的小成本片）
- 學習新語言（目標每年完成一個 A1 級別）
- 散步並拍下街角的招牌字體
- 嘗試做沒做過的料理（每週一道沒看過的食譜）

## 口頭禪
- 「欸欸欸這個我也想試試！」
- 「⋯⋯讓我想一下喔」
- 「謝謝你陪我到這裡」
- 「{signature_prop.split('（')[0].strip()}今天也在喔」  # 跟簽名 prop 綁定的開場白

## 直播風格建議
適合做雜談 + 輕度遊戲（解謎類、節奏類、Cozy 類）+ 偶爾的歌回。
這種組合讓 {nick} 的個性能自然展開，又不會被高強度競技遊戲打亂節奏。
節目企劃點子：
1. 「{nick} 的深夜信箱」——回覆觀眾匿名來信並聊個人想法
2. 「一起學一個新東西」——每週挑一個技能短期速成並分享過程
3. 「跟 {signature_prop.split('（')[0].strip()} 出門散步」——把簽名 prop 帶出門拍下沿途的觀察

## 與觀眾互動方式
稱呼粉絲為「{nick}的朋友」（不用「家人」這種大詞，保留適當距離感）。
互動語氣偏溫和、會記得常駐觀眾的暱稱。收到 SC 會稍微停頓再認真回應，
不會誇張感謝但會讓人感覺被看見。應援方式偏向「一起做」而非「一起喊」，
例如鼓勵觀眾分享自己的小成就，或邀請大家拿出自己的「日常小 prop」一起入鏡。
"""


# ---------------- 主類別 ---------------- #


class PersonaGenerator:
    """產生 VTuber 人設的 markdown。可獨立使用，亦可共享 PromptBuilder 的 Ollama 連線。

    若指定 `preferred_model`（如 "qwen2.5:3b"）會在 chat 時 override session 的 model 名稱
    （Ollama 會自動載入該 model；只要 VRAM 充足就能與 gemma4:e2b 並存）。
    qwen2.5:3b 對中文長文章節輸出穩定度高於 gemma4:e2b。
    """

    def __init__(
        self,
        request_timeout_seconds: int = 120,
        preferred_model: str | None = None,
    ):
        """
        Args:
            request_timeout_seconds: timeout 比 prompt 長（persona 輸出 token 多）
            preferred_model: 若指定，覆蓋共享 session 的模型名（如 "qwen2.5:3b"）
        """
        self._timeout = request_timeout_seconds
        self._preferred_model = preferred_model

    # ---------- 共享 Ollama 連線（由 orchestrator 在 prompt 之後呼叫）---------- #

    def generate_with_session(self, info: OllamaSession, form: FormInput) -> str:
        """已有 warmed Ollama session 時呼叫；不做 acquire 但會在 override model 用完時 unload。

        Returns:
            完整 markdown 字串（含七個章節）。失敗時回傳 template fallback。
        """
        try:
            md = self._chat(info, form)
            self._validate_or_raise(md)
            # 反套路 regex 驗證：LLM 雖被告知禁用，仍可能 fallback 到訓練偏見
            banned = _contains_banned_trope(md)
            if banned:
                _log.warning(
                    "Persona LLM produced banned trope {!r} — replacing with anti-trope template",
                    banned,
                )
                return _template_persona(form)
            return md
        except Exception as e:  # noqa: BLE001
            _log.warning(
                "Persona LLM failed ({}: {}) — using template fallback (anti-trope safe)",
                type(e).__name__, e,
            )
            return _template_persona(form)
        finally:
            # 若用了 override model（如 qwen2.5:3b），必須在 persona 完成時主動卸載，
            # 否則它會跟 session 主 model 雙駐留，後續 SDXL 載入會爆 VRAM。
            if self._preferred_model and self._preferred_model != info.model:
                self._force_unload_override(info)

    # ---------- 純檔案 I/O（與 LLM 無關）---------- #

    @staticmethod
    def save(markdown_text: str, path: Path) -> Path:
        """寫到磁碟；自動建父目錄。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown_text, encoding="utf-8")
        _log.info("📜 Persona written → {}", path)
        return path

    @staticmethod
    def template_fallback(form: FormInput) -> str:
        """公開 fallback；測試與離線 demo 都能直接拿。"""
        return _template_persona(form)

    # ---------- internal ---------- #

    def _chat(self, info: OllamaSession, form: FormInput) -> str:
        user_msg = self._format_user_message(form)
        # 若使用者指定不同模型（e.g. qwen2.5:3b 對中文長文較穩），在 chat 時 override
        chat_model = self._preferred_model or info.model
        if chat_model != info.model:
            _log.info(
                "Persona using preferred_model={} (overrides session model={})",
                chat_model, info.model,
            )
        payload = {
            "model": chat_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "stream": False,
            "keep_alive": -1,
            "options": {
                # 適合長文輸出的設定
                "temperature": 0.85,
                "top_p": 0.95,
                "num_predict": 1500,
            },
        }
        # qwen3 系列：關 thinking mode（persona 不需要 CoT，省 30-60s；
        # 只對 qwen3 送 — 不支援 thinking 的模型收到 think 參數會報錯）
        if chat_model.startswith("qwen3"):
            payload["think"] = False
        r = info.session.post(
            f"{info.base_url}/api/chat",
            json=payload,
            timeout=self._timeout,
        )
        r.raise_for_status()
        body = r.json()
        content = body.get("message", {}).get("content", "")
        return self._post_process(content)

    def _force_unload_override(self, info: OllamaSession) -> None:
        """送 keep_alive=0 給 override model 強制卸載 + 輪詢 /api/ps 確認。

        關鍵：preferred_model 不是被 ModelLoader 管理的，沒這個函式它會駐留
        直到 Ollama default keep_alive timeout（5min），期間 SDXL 載入會爆 VRAM。
        """
        import time
        try:
            info.session.post(
                f"{info.base_url}/api/generate",
                json={"model": self._preferred_model, "prompt": "", "keep_alive": 0, "stream": False},
                timeout=info.timeout_seconds,
            )
        except Exception as e:  # noqa: BLE001
            _log.warning("Persona override unload request failed: {}", e)

        # 輪詢確認真的卸載
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                r = info.session.get(f"{info.base_url}/api/ps", timeout=5)
                r.raise_for_status()
                models = r.json().get("models", [])
                still_loaded = any(
                    m.get("name") == self._preferred_model
                    or m.get("name", "").startswith(self._preferred_model.split(":")[0] + ":")
                    for m in models
                )
                if not still_loaded:
                    _log.info("✓ Persona override model {} unloaded; VRAM freed", self._preferred_model)
                    return
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.3)
        _log.warning(
            "Persona override model {} still loaded after 10s; SDXL may OOM",
            self._preferred_model,
        )

    @staticmethod
    def _format_user_message(form: FormInput) -> str:
        return json.dumps(
            {
                "nickname": form.nickname,
                "hair_color_hex": form.hair_color_hex,
                "hair_length": form.hair_length.value,
                "hair_style": form.hair_style.value,
                "eye_color_hex": form.eye_color_hex,
                "eye_shape": form.eye_shape.value,
                "style": form.style.value,
                "personality": form.personality.value,
                "extra_freeform": form.extra_freeform,
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _post_process(content: str) -> str:
        """清掉常見的 markdown 圍欄與開場白。"""
        text = content.strip()
        # qwen3 保險：think=False 下不該出現，但殘留的 <think>…</think> 一律剝掉
        text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()
        # 去掉 ```markdown ... ``` 包裝
        text = re.sub(r"^```(?:markdown|md)?\s*\n", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n```\s*$", "", text)
        # 如果第一行不是 ## 開頭，嘗試從第一個 ## 開始截
        first_heading = text.find("## ")
        if first_heading > 0:
            text = text[first_heading:]
        return text.strip() + "\n"

    _REQUIRED_HEADINGS = (
        "## 基本資料",
        "## 個性詳細",
        "## 背景故事",
        "## 興趣與嗜好",
        "## 口頭禪",
        "## 直播風格建議",
        "## 與觀眾互動方式",
    )

    @classmethod
    def _validate_or_raise(cls, md: str) -> None:
        """缺章節 → 視為 LLM 失敗 → 由上層 fallback。"""
        missing = [h for h in cls._REQUIRED_HEADINGS if h not in md]
        if missing:
            raise ValueError(f"persona markdown missing headings: {missing}")
        if len(md) < 400:
            raise ValueError(f"persona markdown too short: {len(md)} chars")
