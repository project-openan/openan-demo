import LayerView from '../LayerView';
import { useStory } from '../../storyline/StorylineContext';
import { root } from '../../design/regions/flow-chart';
import { regionFitStyle, ZOOM } from '../../storyline/roles';

// 流程图区域：区域 div 承担 V2.12 面板收起重适配 F（过渡 0.25s）；
// V2.21 用户缩放回归画布区域级——.fc-zoom 施加 scale(z)，原点为画布中心 ZOOM.center 的区域本地
// 坐标（1112.5−305, 470.5−48）＝(807.5,422.5)；无过渡（与覆盖层内层 .st-zoomz/固定节点反向同步瞬时）。
// 点阵背景/缩放工具栏/回放按钮组由 uiPatches 反向变换抵消收起 F 与缩放 Z（保持设计尺寸原位不随动）
export default function FlowChartRegion() {
  const pub = useStory();
  const fit = pub ? regionFitStyle(pub) : undefined;
  const z = pub && pub.zoom ? pub.zoom : 1;
  const zstyle = z !== 1
    ? {
        transform: 'scale(' + z + ')',
        transformOrigin: (ZOOM.center[0] - root.x) + 'px ' + (ZOOM.center[1] - root.y) + 'px',
      }
    : undefined;
  return (
    <div data-node={root.name} style={{
      position: 'absolute',
      left: root.x + 'px',
      top: root.y + 'px',
      width: root.w + 'px',
      height: root.h + 'px',
      overflow: root.clip ? 'hidden' : undefined,
      ...root.style,
      transition: 'transform 0.25s ease', // 与 .st-zoomwrap 外层同步动画（收起/展开回位不错帧）
      ...fit,
    }}>
      <div className="fc-zoom" style={zstyle}>
        {root.children.map((c) => <LayerView key={c.id} node={c} />)}
      </div>
    </div>
  );
}
