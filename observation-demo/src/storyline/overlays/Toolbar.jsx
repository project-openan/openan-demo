// Toolbar.jsx — 工具栏透明点击层（回放/单步/倍速/停止）+ 倍速下拉 + 播放态暂停图标
// V5.57 曾在按钮内叠覆盖层文字（.st-tbtn-text）与设计烤入文字「回放」（23:137028）
// 重合（用户反馈"2 个重合的"）——V5.58 废止覆盖层，文字切换改由 roles.js 补丁
// 直接改写设计文字节点（暂停/回放）
import React, { useState } from 'react';
import { BUTTONS } from '../roles';
import { T, getLang } from '../../i18n';

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
        title={playing ? T('btn.pause') : T('btn.replay')} aria-label={playing ? T('btn.pause') : T('btn.replay')} />
      <button className="st-tbtn" style={boxStyle(BUTTONS.step.box)} onClick={api.stepOnce}
        title={T('btn.step')} aria-label={T('btn.step')} />
      <button className="st-tbtn" style={boxStyle(BUTTONS.speed.box)} onClick={() => setMenu((m) => !m)}
        title={T('btn.speed')} aria-label={T('btn.speed')} />
      <button className="st-tbtn" style={boxStyle(BUTTONS.stop.box)} onClick={api.stop}
        title={T('btn.stop')} aria-label={T('btn.stop')} />
      {/* V6.81（用户规格）：EN 播放键图标左移居中（i18n.css 23:137022）——暂停覆盖层同步 */
      }
      {playing ? (
        <div className="st-pauseicon" style={{ left: pb.x + (getLang() === 'en' ? 6 : 14), top: pb.y + 8 }}><span /><span /></div>
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

