import React from 'react'

export default function PlatformNodeCard() {
  return (
    <div className="platform-card">
      <img className="p-abs" src="/assets/ic-roma.svg" alt="" style={{ left: 56, top: 12, width: 32, height: 32 }} />
      <span className="platform-card__name" style={{ left: 44, top: 52 }}>能开平台</span>
      {/* V5.55（用户规格）：注册中心子卡高度统一 2rem（48→32）、图标缩至 1.5rem（32→24，
          垂直居中）——与 ZX 卡内编排中心卡（roles uiPatches）同款规格 */}
      <div className="platform-card__sub" style={{ left: 12, top: 82, width: 120, height: 32 }}>
        <img className="p-abs" src="/assets/ic-checkin.svg" alt="" style={{ left: 12, top: 4, width: 24, height: 24 }} />
        <span className="platform-card__subname" style={{ left: 52, top: 5 }}>注册中心</span>
      </div>
    </div>
  )
}
