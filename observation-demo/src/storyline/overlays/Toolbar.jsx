// Toolbar.jsx — 工具栏透明点击层（回放/单步/倍速/停止）+ 倍速下拉 + 播放态暂停图标
// V5.57（用户规格）：回放按钮显示文字并随状态切换——播放中「暂停」、其余「回放」
//（原仅悬浮 title + 播放中暂停图标；文字与图标并存：图标左（+14）、文字接其右）
import React, { useState } from 'react';
import { BUTTONS } from '../roles';

const SPEEDS = [0.5, 1, 2, 4, 8, 16];
const boxStyle = (b) => ({ left: b.x, top: b.y, width: b.w, height: b.h });

export default function Toolbar({ pub }) {
  const { api, mode, speed } = pub;
  const [menu, setMenu] = useState(false);
  const playing = mode === 'playing';
  const pb = BUTTONS.play.box;
  return (
    <div className="st-layer st-toolbar">
      <button className="st-tbtn" style={boxStyle(BUTTONS.play.box)} onClick={api.play}
        title={playing ? '暂停' : '回放'} aria-label={playing ? '暂停' : '回放'}>
        <span className="st-tbtn-text" style={{ left: playing ? 36 : 22, top: 6 }}>{playing ? '暂停' : '回放'}</span>
      </button>
      <button className="st-tbtn" style={boxStyle(BUTTONS.step.box)} onClick={api.stepOnce}
        title="单步" aria-label="单步" />
      <button className="st-tbtn" style={boxStyle(BUTTONS.speed.box)} onClick={() => setMenu((m) => !m)}
        title="倍速" aria-label="倍速" />
      <button className="st-tbtn" style={boxStyle(BUTTONS.stop.box)} onClick={api.stop}
        title="停止" aria-label="停止" />
      {playing ? (
        <div className="st-pauseicon" style={{ left: pb.x + 14, top: pb.y + 8 }}><span /><span /></div>
      ) : null}
      {menu ? (
        <div className="st-speedmenu" style={{ left: BUTTONS.speed.box.x, top: BUTTONS.speed.box.y + 32 }}>
          {SPEEDS.map((s) => (
            <div key={s} className={'st-speeditem' + (s === speed ? ' st-speeditem-cur' : '')}
              onClick={() => { api.setSpeed(s); setMenu(false); }}>
              {s}x{s === speed ? ' ✓' : ''}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

