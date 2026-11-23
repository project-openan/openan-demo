// useStageClock.js — 面板分步时钟（V3.22 抽自 IntentRecognitionPanel）
// 窗口内世界态无事件（pub 仅在事件边界发布），面板以内部 RAF 推进 phase（业务秒）：
// playing 时按 speed/timeScale 将墙钟折算业务秒（dt 截断 0.1s，与 StorylineProvider
// 播放环一致——标签页隐藏时 RAF 同停，两钟不漂移）；暂停/seek 挂载直接落到对应步。
// V3.23：可选 weights（长度 = steps 的比例数组）替代均分——各步按权重占窗口，
// 边界与 panel-timing.js panelStageBeats 同源（单步节拍与面板分步对齐）。
import { useEffect, useRef, useState } from 'react'

export default function useStageClock({ t0 = 0, t1 = 1, t = t0, mode = 'playing', speed = 1, timeScale = 0.25 }, steps, weights) {
  const dur = Math.max(0.001, t1 - t0)
  const w = Array.isArray(weights) && weights.length === steps ? weights : null
  const stageAt = (phase) => {
    if (dur <= 0) return steps
    const frac = phase / dur
    if (!w) return Math.min(steps, Math.floor(frac * steps) + 1)
    let acc = 0
    for (let k = 1; k <= steps; k++) { acc += w[k - 1]; if (frac < acc) return k }
    return steps
  }
  const [stage, setStage] = useState(() => stageAt(Math.max(0, Math.min(t - t0, dur))))
  const ref = useRef(stage)
  useEffect(() => {
    let phase = Math.max(0, Math.min(t - t0, dur))
    const apply = () => {
      const s = stageAt(phase)
      if (s !== ref.current) { ref.current = s; setStage(s) }
    }
    apply()
    if (mode !== 'playing' || phase >= dur) return undefined
    let raf = 0
    let last = performance.now()
    const tick = (now) => {
      phase = Math.min(phase + Math.min((now - last) / 1000, 0.1) * (speed || 1) / timeScale, dur)
      last = now
      apply()
      if (phase < dur) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [t0, t1, t, mode, speed, timeScale, dur])
  return stage
}

