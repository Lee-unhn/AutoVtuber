"""VRMBlendshapeWriter — 給 VRM 0.x 加 52 個 ARKit Perfect Sync blendshape clips。

VRM 0.x 的 blendShapeMaster.blendShapeGroups 預設只有 ~15 個（VRoid 標準 + 些客製）。
**Perfect Sync** 是業界 VTuber 標準（Warudo / VSeeFace / VTube Studio）— 用 52 個
ARKit 命名的 blendshape clip 跟 ARKit / mediapipe blendshape v2 對接。

我們不替換底層 mesh（VRoid mesh 沒對應 52 個 morph target），而是把 52 個 ARKit
名稱 bind 到既有 VRoid morph 的近似組合：

    mouthSmileLeft  → Joy 的 60% strength
    mouthFrownRight → Sorrow 的 60%
    eyeBlinkLeft    → Blink_L 的 100%
    jawOpen         → A 的 100%
    ...

這樣使用者把 .vrm 載入 Warudo / VSeeFace 開 Perfect Sync streamer，會看到 ARKit
weights 直接驅動 VRoid morph，雖然「不像有 52 morph 那麼細」但**體驗對齊業界**。

依據：
    https://malaybaku.github.io/VMagicMirror/en/tips/perfect_sync/
    https://docs.warudo.app/docs/mocap/face-tracking
    https://github.com/hinzka/52blendshapes-for-VRoid-face
"""
from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from ..utils.logging_setup import get_logger

if TYPE_CHECKING:
    from .vrm_io import VRMFile

_log = get_logger(__name__)


# ARKit 52 名稱 → (對應 VRoid blendshape group name, 強度 0-100)
# strength 是「目標 morph 在 1.0 weight 時，這個 ARKit clip 應該套幾 %」
# None = 沒對應的 morph，clip 仍存在但 binds 為空（VSeeFace 看到名稱但無 deformation）
ARKIT_TO_VROID: list[tuple[str, str | None, int]] = [
    # Eye blink (精確對應)
    ("eyeBlinkLeft", "Blink_L", 100),
    ("eyeBlinkRight", "Blink_R", 100),
    # Eye look — VRoid 預設沒個別 morph，用 0 weight（clip 保留命名相容）
    ("eyeLookUpLeft", None, 0),
    ("eyeLookDownLeft", None, 0),
    ("eyeLookInLeft", None, 0),
    ("eyeLookOutLeft", None, 0),
    ("eyeLookUpRight", None, 0),
    ("eyeLookDownRight", None, 0),
    ("eyeLookInRight", None, 0),
    ("eyeLookOutRight", None, 0),
    # Eye squint/wide
    ("eyeSquintLeft", "Joy", 30),    # 微笑時眼睛微瞇
    ("eyeSquintRight", "Joy", 30),
    ("eyeWideLeft", "Surprised", 100),
    ("eyeWideRight", "Surprised", 100),
    # Jaw
    ("jawForward", None, 0),
    ("jawLeft", None, 0),
    ("jawRight", None, 0),
    ("jawOpen", "A", 100),            # 嘴大開
    # Mouth shape
    ("mouthClose", None, 0),
    ("mouthFunnel", "U", 80),         # 噘嘴漏斗
    ("mouthPucker", "U", 100),
    ("mouthLeft", None, 0),
    ("mouthRight", None, 0),
    # Mouth emotional
    ("mouthSmileLeft", "Joy", 60),
    ("mouthSmileRight", "Joy", 60),
    ("mouthFrownLeft", "Sorrow", 60),
    ("mouthFrownRight", "Sorrow", 60),
    ("mouthDimpleLeft", "Joy", 30),
    ("mouthDimpleRight", "Joy", 30),
    ("mouthStretchLeft", "I", 50),
    ("mouthStretchRight", "I", 50),
    # Mouth roll/shrug — 沒對應
    ("mouthRollLower", None, 0),
    ("mouthRollUpper", None, 0),
    ("mouthShrugLower", None, 0),
    ("mouthShrugUpper", None, 0),
    # Mouth press / lower-down / upper-up
    ("mouthPressLeft", "I", 30),
    ("mouthPressRight", "I", 30),
    ("mouthLowerDownLeft", "A", 30),
    ("mouthLowerDownRight", "A", 30),
    ("mouthUpperUpLeft", "A", 30),
    ("mouthUpperUpRight", "A", 30),
    # Brow
    ("browDownLeft", "Angry", 80),
    ("browDownRight", "Angry", 80),
    ("browInnerUp", "Sorrow", 80),
    ("browOuterUpLeft", "Surprised", 60),
    ("browOuterUpRight", "Surprised", 60),
    # Cheek
    ("cheekPuff", "Fun", 80),
    ("cheekSquintLeft", "Joy", 40),
    ("cheekSquintRight", "Joy", 40),
    # Nose
    ("noseSneerLeft", "Angry", 30),
    ("noseSneerRight", "Angry", 30),
    # Tongue (VRoid 預設沒舌頭 morph)
    ("tongueOut", None, 0),
]

assert len(ARKIT_TO_VROID) == 52, "ARKit Perfect Sync 標準是 52 個"


class VRMBlendshapeWriter:
    """加 ARKit Perfect Sync clips 到 VRM extension。"""

    @staticmethod
    def add_arkit_clips(vrm: "VRMFile") -> int:
        """把 52 個 ARKit blendshape group 加到 vrm.raw.extensions['VRM']['blendShapeMaster']['blendShapeGroups']。

        Args:
            vrm: VRMFile（已 load）

        Returns:
            新增的 group 數量（理論是 52，但若某些已存在會跳過）

        無 side effect 在 disk 上 — 呼叫者要自己 vrm.save() 才寫檔。
        """
        gltf = vrm.raw
        if not gltf.extensions:
            _log.warning("VRM has no extensions block; skipping ARKit clips")
            return 0
        vrm_ext = gltf.extensions.get("VRM")
        if not vrm_ext:
            _log.warning("No VRM extension found; not a VRM 0.x file?")
            return 0
        bsm = vrm_ext.get("blendShapeMaster")
        if not bsm:
            _log.warning("No blendShapeMaster; cannot add ARKit clips")
            return 0
        existing_groups = bsm.get("blendShapeGroups", [])

        # 建查表 name → binds（用 name 而非 presetName，因為 Surprised/Extra 用 unknown preset）
        name_to_binds: dict[str, list] = {
            grp.get("name", ""): grp.get("binds", [])
            for grp in existing_groups
        }
        existing_names: set[str] = {grp.get("name", "") for grp in existing_groups}

        added = 0
        for arkit_name, vroid_target, strength in ARKIT_TO_VROID:
            if arkit_name in existing_names:
                continue  # 已有同名 clip，不覆蓋
            base_binds = name_to_binds.get(vroid_target, []) if vroid_target else []
            # 縮放 binds 的 weight
            scaled_binds = []
            for b in base_binds:
                scaled = deepcopy(b)
                # b 可能是 dict 或 pygltflib 物件；正規化成 dict
                if hasattr(b, "weight"):
                    scaled = {
                        "mesh": b.mesh,
                        "index": b.index,
                        "weight": b.weight * strength / 100.0,
                    }
                else:
                    scaled["weight"] = b.get("weight", 100.0) * strength / 100.0
                scaled_binds.append(scaled)

            new_group = {
                "name": arkit_name,
                "presetName": "unknown",  # ARKit name 不在 VRM 0.x 預設 preset 列表
                "binds": scaled_binds,
                "materialValues": [],
                "isBinary": False,
            }
            existing_groups.append(new_group)
            added += 1

        bsm["blendShapeGroups"] = existing_groups
        _log.info(
            "Added {} ARKit Perfect Sync clips to VRM (total now {})",
            added, len(existing_groups),
        )
        return added
