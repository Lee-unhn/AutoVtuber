# 🎨 Prompt Engineering — SDXL Anime Portrait Templates

> PromptBuilder 透過 Ollama 把使用者表單轉成 SDXL prompt。
> 本檔案記錄每個欄位的 tag 對應、negative prompt 庫、以及測試用 prompt 範本。

---

## SDXL（AnimagineXL 4.0）核心咒語

**永遠包含** 在 positive：
```
masterpiece, best quality, very aesthetic, absurdres, 1girl,
looking at viewer, upper body, white background, clean lighting
```

**永遠包含** 在 negative：
```
nsfw, lowres, bad anatomy, bad hands, text, error,
missing fingers, extra digit, fewer digits, cropped,
worst quality, low quality, normal quality, jpeg artifacts,
signature, watermark, username, blurry,
multiple views, side view, back view
```

---

## 欄位 → Booru tag 對應

### 髮色 (`hair_color_hex`)
表單值是 hex 顏色；Ollama 應該轉換成最接近的 booru 色名 + 也保留 hex 提示：
- `#0F0F0F` → `black hair`
- `#5B3A29` → `brown hair`
- `#C9B89B` → `light brown hair, beige hair`
- `#FFD700` → `blonde hair`
- `#C0C0C0` → `silver hair, platinum hair`
- `#FF69B4` → `pink hair`
- `#9370DB` → `purple hair, lavender hair`
- `#4169E1` → `blue hair`
- `#228B22` → `green hair`
- `#FF4500` → `red hair, orange hair`

### 髮長 (`hair_length`)
- `short` → `short hair`
- `medium` → `medium hair`
- `long` → `long hair`
- `very_long` → `very long hair, hair past waist`

### 髮型 (`hair_style`)
- `straight` → `straight hair`
- `wavy` → `wavy hair`
- `curly` → `curly hair`
- `ponytail` → `ponytail`
- `twin_tails` → `twintails`
- `bun` → `hair bun, bun`
- `braided` → `braid, braided hair`

### 眼色 (`eye_color_hex`)
類似髮色映射：
- `#3B5BA5` → `blue eyes`
- `#228B22` → `green eyes`
- `#8B4513` → `brown eyes`
- `#FFD700` → `yellow eyes, golden eyes`
- `#9370DB` → `purple eyes, violet eyes`
- `#DC143C` → `red eyes, crimson eyes`
- `#A9A9A9` → `grey eyes, silver eyes`

### 眼形 (`eye_shape`)
- `round` → `round eyes, big eyes`
- `almond` → 不加額外 tag（預設）
- `sharp` → `sharp eyes, narrow eyes`
- `sleepy` → `sleepy eyes, half-closed eyes`

### 風格 (`style`)
- `anime_modern` → 不加額外 tag（AnimagineXL 預設）
- `anime_classic` → `90s anime style, retro anime`
- `chibi` → `chibi, cute, deformed proportions`
- `cyberpunk` → `cyberpunk, neon lights, futuristic, tech wear`
- `cottagecore` → `cottagecore, soft lighting, pastoral, vintage dress`
- `semi_realistic` → `semi-realistic, detailed shading, refined features`

### 個性 → 表情/姿態微調
（MVP1 不影響生成，但 prompt 中可加微妙變化以增強角色感）
- `cheerful_outgoing` → `smile, cheerful expression, energetic pose`
- `calm_introverted` → `soft smile, calm expression, neutral pose`
- `shy_gentle` → `blush, gentle smile, hands together`
- `confident_leader` → `confident smile, hands on hips, strong pose`
- `playful_teasing` → `smirk, playful expression, head tilted`
- `caring_nurturing` → `gentle smile, soft expression`
- `mysterious_cool` → `cool expression, hooded eyes, half smile`
- `energetic_chaotic` → `excited expression, open mouth, dynamic pose`
- `serious_focused` → `serious expression, focused gaze`
- `dreamy_artistic` → `dreamy expression, looking up, gentle blush`
- `analytical_logical` → `thoughtful expression, narrowed eyes`
- `adventurous_brave` → `determined smile, hands on hips`
- `kind_harmonious` → `warm smile, soft eyes`
- `proud_noble` → `confident expression, regal pose, raised chin`
- `curious_childlike` → `wide eyes, curious expression, slight smile`
- `quiet_observant` → `neutral expression, calm gaze`

---

## Few-shot 範本（給 Ollama）

PromptBuilder 用以下 system prompt 教模型輸出格式：

```
You are an SDXL anime portrait prompt engineer for VTuber model generation.
Output exactly two lines, no other text:
POSITIVE: <comma-separated booru-style tags>
NEGATIVE: <comma-separated booru-style tags>

Rules for POSITIVE:
- Always include: masterpiece, best quality, very aesthetic, absurdres
- Single front-facing character, upper body, looking at viewer
- Plain white background, clean lighting, no shadows on face
- Use the user's hair color, hair style, eye color, eye shape, personality flavor
- Translate freeform field to tags faithfully

Rules for NEGATIVE:
- Always include: nsfw, lowres, bad anatomy, bad hands, multiple views, side view, back view
```

範例輸入 → 輸出對：

**Input:**
```json
{
  "hair_color_hex": "#5B3A29",
  "hair_length": "long",
  "hair_style": "straight",
  "eye_color_hex": "#3B5BA5",
  "eye_shape": "almond",
  "style": "anime_modern",
  "personality": "calm_introverted",
  "extra_freeform": "圍巾, 冬天"
}
```

**Expected output:**
```
POSITIVE: 1girl, brown hair, long hair, straight hair, blue eyes, soft smile, calm expression, scarf, winter clothing, looking at viewer, upper body, white background, clean lighting, masterpiece, best quality, very aesthetic, absurdres
NEGATIVE: nsfw, lowres, bad anatomy, bad hands, multiple views, side view, back view, summer, swimsuit
```

---

## 容錯解析

`PromptBuilder._parse_response` 處理三種情況：
1. **嚴格格式**（POSITIVE: ... / NEGATIVE: ...）→ 直接 regex 抓
2. **兩行純 prompt**（沒寫 POSITIVE: 標籤）→ 第一行當 positive，第二行當 negative
3. **只有一行或空** → 用安全預設 prompt

確保即使 Ollama 模型不聽話也不會崩潰。

---

## 種子管理

- `JobSpec.form.seed = -1`（預設）→ 隨機種子，每次都不同
- `seed = <非負整數>` → 固定，可重現結果（preset 重生成時用）
- 種子記錄在 `JobResult.prompt.seed`，preset 儲存時保留
