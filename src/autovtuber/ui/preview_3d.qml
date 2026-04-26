// AutoVtuber 3D 預覽器 — QtQuick3D View3D + 旋轉/縮放控制。
//
// 由 preview_3d.py 的 Python 端透過 setSource() 載入。
// 可載入 .vrm （VRoid 匯出的 glTF binary，QtQuick3D 部分支援）
// 或 fallback 到顯示「Preview placeholder」訊息。

import QtQuick
import QtQuick3D
import QtQuick3D.Helpers

Rectangle {
    id: root
    color: "#1e1e1e"

    property string vrmPath: ""
    property real cameraDistance: 1.6

    View3D {
        id: view
        anchors.fill: parent

        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Color
            clearColor: "#1e1e1e"
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.Medium
        }

        // 相機
        PerspectiveCamera {
            id: cam
            position: Qt.vector3d(0, 1.4, root.cameraDistance)
            eulerRotation.x: -10
        }

        // 三點打光
        DirectionalLight {
            eulerRotation.x: -30
            eulerRotation.y: -25
            brightness: 1.2
        }
        DirectionalLight {
            eulerRotation.x: -10
            eulerRotation.y: 100
            brightness: 0.6
            color: "#ffe9d2"
        }
        DirectionalLight {
            eulerRotation.x: -5
            eulerRotation.y: -160
            brightness: 0.4
            color: "#cfe0ff"
        }

        // 模型容器
        Node {
            id: modelRoot
            // 載入 VRM。若 .vrm 是 binary glTF，QtQuick3D 部分能讀；
            // 完全不能讀時顯示 placeholder cube
            Loader3D {
                visible: root.vrmPath !== ""
                source: root.vrmPath
            }

            // Placeholder（無模型時顯示）
            Model {
                visible: root.vrmPath === ""
                source: "#Cube"
                scale: Qt.vector3d(0.5, 1.6, 0.5)
                materials: PrincipledMaterial {
                    baseColor: "#5a5a5a"
                    roughness: 0.7
                }
            }
        }
    }

    // 滑鼠拖曳旋轉
    MouseArea {
        anchors.fill: parent
        property real lastX: 0
        property real lastY: 0
        onPressed: (mouse) => { lastX = mouse.x; lastY = mouse.y }
        onPositionChanged: (mouse) => {
            if (pressed) {
                modelRoot.eulerRotation.y -= (mouse.x - lastX) * 0.5
                modelRoot.eulerRotation.x -= (mouse.y - lastY) * 0.3
                lastX = mouse.x
                lastY = mouse.y
            }
        }
        onWheel: (wheel) => {
            cam.position.z = Math.max(0.5, Math.min(4.0, cam.position.z - wheel.angleDelta.y * 0.001))
        }
    }

    // 提示訊息
    Text {
        anchors.centerIn: parent
        visible: root.vrmPath === ""
        text: "🎭 預覽器\n生成完成後 .vrm 會在此顯示\n滑鼠拖曳旋轉，滾輪縮放"
        color: "#888"
        font.pixelSize: 14
        horizontalAlignment: Text.AlignHCenter
    }
}
