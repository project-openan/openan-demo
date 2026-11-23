import ScreenCanvas from './components/ScreenCanvas';
import { StorylineProvider } from './storyline/StorylineContext';
import StorylineOverlays from './storyline/overlays/StorylineOverlays';
import BackgroundRegion from './components/regions/BackgroundRegion';
import FlowChartRegion from './components/regions/FlowChartRegion';
import LeftPanelRegion from './components/regions/LeftPanelRegion';
import LogPanelRegion from './components/regions/LogPanelRegion';
import TitleRegion from './components/regions/TitleRegion';
import TopNavRegion from './components/regions/TopNavRegion';
import { useLang, LangToggle } from './i18n';

export default function App() {
  // 语言切换：useLang 订阅变更 → App 整树重渲染（T() 全部重求值）
  useLang();
  // V2.14：Provider 移到 ScreenCanvas 外（画布需读取 pub.vscale 做整页铺满变换），
  // 覆盖层与各区域同在画布内（画布坐标系渲染）
  return (
    <StorylineProvider>
      <ScreenCanvas>
        <BackgroundRegion />
        <FlowChartRegion />
        <TitleRegion />
        <LeftPanelRegion />
        <LogPanelRegion />
        <TopNavRegion />
        <StorylineOverlays />
        <LangToggle />
      </ScreenCanvas>
    </StorylineProvider>
  );
}
