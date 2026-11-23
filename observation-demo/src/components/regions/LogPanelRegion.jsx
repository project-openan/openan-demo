import LayerView from '../LayerView';
import { useStory } from '../../storyline/StorylineContext';
import { root } from '../../design/regions/log-panel';
import { logFitStyle } from '../../storyline/roles';

// 底部 A2A-T协作日志面板
// V2.12：全画布包裹层（0,0 起，子节点保持画布坐标不变）——pointer-events:none 不拦截
// 其余区域交互（把手经 uiPatches 补 pointer-events:auto 重新可点）；
// 左栏收起时随画布同步左向拉伸（右缘 1920 锚定，与流程图区域重适配一致；V3.2 面板扩至 1615）
export default function LogPanelRegion() {
  const pub = useStory();
  const fit = pub ? logFitStyle(pub, 0) : undefined;
  return (
    <div style={{
      position: 'absolute',
      left: 0,
      top: 0,
      width: '1920px',
      height: '1080px',
      pointerEvents: 'none',
      transition: 'transform 0.25s ease',
      ...fit,
    }}>
      <LayerView node={root} />
    </div>
  );
}
