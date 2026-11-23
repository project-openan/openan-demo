// OrderPanel.jsx — V6.0 流式布局：工单区域工单卡（覆盖层流式组件）
// 设计工单卡子树（ORDERS.c1/c2）整组隐藏（roles.js FLOW_HIDE），本组件按同一列表槽位
//（24,170 起、卡 256×142、间距 16）重建，卡内纵向流式：工单号 → [图标+客户名+状态胶囊] →
// 描述（两行截断）→ 时间行（margin-top:auto 贴底）。选中态/角标/回放中胶囊/搜索与状态
// 过滤（orderVisible）/整卡点击切换案例（拖拽守卫）口径与 buildPatches/makeInteractions 一致。
import React, { useRef } from 'react';
import { ORDERS, orderVisible } from '../roles';
import { CASES } from '../cases';
import WorkOrderDetailPanel from '../../components/panels/WorkOrderDetailPanel.jsx';
import { CASE_INPUT } from '../../components/panels/IntentRecognitionPanel.jsx';
import { T } from '../../i18n';
import './flow.css';

// 受理时间行（设计烤入文案：日期｜用时N分钟）
const TIMES = {
  c1: '10-24 02:18:05｜用时173分钟',
  c2: '10-28 10:20:08｜用时39分钟',
};
// 卡图标（V5.44：两卡同款医院图标）
const ICONS = { c1: '/icons/ic_ebg_hospital.svg', c2: '/icons/ic_ebg_hospital.svg' };
// V6.57→V6.58（用户规格）：单位名称非敏感信息——客户/集团名称恢复明文；
// 敏感信息仅静态工单描述中的门牌地址与联系电话（随源数据打码，见 STATIC_ORDERS）

// V6.32（用户规格）：工单展开详情数据——工单描述/归属地市/归属区县与投诉识别面板
// 同源（IntentRecognitionPanel CASE_INPUT：投诉现象文案 + 客户所在地「广州市X区…」解析）；
// 集团名称 = 工单客户；
// V6.43（用户规格）：头部第一行【热线客服受理-智能】改为【工单标题】；集团编号→产品编号；
// 故障地点→投诉时间
// V6.44（用户规格）：按《故事线工单详情》补全标题/产品编码/投诉时间（全文年月日格式；
// c2 标题取文档末条，c1 标题按同号工单前缀+案例客户名归纳）
const ORDER_TITLES = {
  c1: 'ot.c1',
  c2: 'ot.c2',
};
const orderDetailData = (k) => {
  const [phen] = CASE_INPUT[k === 'c1' ? 'c1' : 'c2'];
  // V6.66（用户规格）：弹窗全表单化——标题/描述改信息行（工单标题/投诉信息），
  // 原标题行【工单标题】前缀废止；
  // V6.75→V6.78（用户规格）：地址/编号隐藏改随机虚拟数据（*** 不可读）——
  // 归属市区县按案、产品编号两案同号（与投诉识别面板/Task-T 同源）
  const AREA = { c1: ['广州市', '云溪区'], c2: ['广州市', '松岚区'] };
  return {
    title: ORDER_TITLES[k],
    desc: T(phen).replace(T('ir.symptomPrefix'), ''),
    area: [
      { label: 'om.city', value: AREA[k][0] },
      { label: 'om.district', value: AREA[k][1] },
      { label: 'om.product', value: '30122075634' },
    ],
  };
};

function OrderCard({ k, pub, bc }) {
  const d = useRef({ x: 0, y: 0 });
  const c = CASES[k];
  const selected = pub.caseId === k;
  const expanded = pub.orderDetail === k;
  const playing = !pub.world ? false : !pub.world.caseDone;
  const pill = selected && playing
    ? { text: '回放中', bg: 'rgba(92,172,255,0.15)', fg: 'rgba(92,172,255,1)' } // V5.32 蓝系
    : { text: '已完成', bg: 'rgba(9,170,113,0.15)', fg: 'rgba(54,193,141,1)' };
  return (
    <div className="fl-order" style={{ border: '1px solid ' + bc }}
      onPointerDown={(e) => { d.current = { x: e.clientX, y: e.clientY }; }}
      onClick={(e) => {
        if (Math.abs(e.clientX - d.current.x) > 5 || Math.abs(e.clientY - d.current.y) > 5) return;
        const sel = window.getSelection ? window.getSelection() : null;
        if (sel && String(sel).length > 0) return;
        pub.api.selectCase(k);
      }}>
      {selected ? (
        <div className="fl-order__check"><img src="/icons/ic_selected.svg" alt="" draggable={false} /></div>
      ) : null}
      {/* V6.2（用户规格）：三行内容（行距 0.5rem）——工单号 / 单位名称行 / 末行
          （时间 + 详情按钮）；V6.63：展开内嵌详情面板改弹窗呈现 */}
      <div className="fl-order__no">{c.orderNo}</div>
      <div className="fl-order__row">
        <img src={ICONS[k]} alt="" draggable={false} />
        <span className="fl-order__cust" title={T(c.customer)}>{T(c.customer)}</span>
        <span className="fl-order__pill" style={{ background: pill.bg, color: pill.fg }}>{T(pill.text)}</span>
      </div>
      <div className="fl-order__last">
        <span className="fl-order__time">{T(TIMES[k])}</span>
        {/* V6.63（用户规格）：详情按钮——弹窗呈现（无角标图标）；
            点击开/再点关（stopPropagation 不触发整卡切案） */}
        <span
          className={'fl-order__detail' + (expanded ? ' fl-order__detail--open' : '')}
          onClick={(e) => { e.stopPropagation(); pub.api.setOrderDetail(expanded ? null : k); }}
        >
          {T('om.details')}
        </span>
      </div>
    </div>
  );
}

// 左尖角 SVG（V6.2：收起把手图标——参考日志面板把手箭头样式，10px 描边尖角；
// V6.2 用户规格：增亮提对比度 #C9C9C9）
const Chevron = () => (
  <svg width="0.625rem" height="0.625rem" viewBox="0 0 10 10" style={{ transform: 'rotate(180deg)' }} aria-hidden="true">
    <path d="M3 1.5 L7.5 5 L3 8.5" fill="none" stroke="rgba(201,201,201,1)" strokeWidth="1.4"
      strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);

// V6.37/40（用户规格）：静态展示工单卡（V6.73 起 ×5）——列于现有两卡下方，卡体不支持点击
// （无选中/切案/过滤联动）；展开支持（V6.40）——演示数据详情面板与真卡同款
// （WorkOrderDetailPanel），与真卡共用 orderDetail 单开互斥
// V6.41（用户规格）：静态工单数据定稿（用户提供——工单号/单位/受理时间/描述/
// 归属地市区县/集团编号；首枚工单号与案例一工单同号）
// V6.42（用户规格）：集团编号一律「无」（仅医院工单 c1 保留设计值，数值已随脱敏移除）
// V6.44（用户规格）：按《故事线工单详情》补全 title/productNo；文档 9 月日期随故事线
// 平移为 10 月（与卡面受理时间一致）；s3/s4 描述按文档修订（处理并回复/维修人员/联系方式）
// V6.57（用户规格）：静态工单描述中的门牌地址与联系电话随源数据打码（* 逐字符）
// V6.58/59（用户规格）：敏感信息脱敏——门牌地址/联系电话/街道地址逐字符 *；
// 政府/军队机构名（s3/s4 客户）打码；普通单位名称按口径保留明文；机房端口名为演示
// 核心业务数据保留
// V6.60（用户规格）：s3/s4 替换为 某储能科技公司（惠州/广州）白名单专线工单（用户提供
// 文案；源文未提供工单号——按既有格式以投诉时间派生（原真实号已随脱敏移除）
// /104930，源文「归属区县 020」保持原样；desc=问题描述/报障描述，用时沿用 5 分钟）
// V6.61（用户规格）：s1 某银行 受理时间改 10-20 01:55:05、s2 某系统集成公司 改 10-18
// （时钟不变）——工单号内嵌日期随之（20261020/20261018）；首枚与案例工单同号关系废止
// V6.62（用户规格）：列表严格按时间倒序——10-12 同日两单对调（10:49:30 广州 先于 09:47:29 惠州）
// V6.67（用户规格）：末枚（惠州白名单）换为 某银行深圳分行工单（源单号已随脱敏移除，2026-10-09 14:54:56——倒序列表仍居末位；源文未提供用时——沿用 5 分钟）
// V6.68（用户规格）：静态工单耗时重排——取值 30–180 分钟、均值≈2.56 小时
// V6.69（用户规格）：某银行单改 35 分钟后其余三张重排——175/145/140＝460，
// 均值 153.3 分 ≈ 2.56h、最大 175 分（2.92h）≤ 3h；c1/c2 故事线用时不改
// V6.73（用户规格）：新增 某集团公司 数据(互联网)专线工单——源单号已随脱敏移除（原 10-28 06:25:41）；投诉时间改 10-22 置某银行单前（倒序仍成立），
// 工单号内嵌日期随之改 20261022（V6.61 口径）；用时 154 分钟——非某银行四张
// 175/145/140/154＝614，均值 153.5 分 ≈ 2.56h 仍达标
// V6.74（用户规格）：客户单位名虚拟化——某医院/某科技公司/某银行/某系统集成公司/
// 某储能科技公司/某银行深圳分行/某集团公司（真实名仅在历史版本注释之外不再留存）；
// V6.75→V6.78（用户规格）：地址/编号隐藏改随机虚拟数据（*** 不可读）——
// city/district 虚拟区名、productNo 每单随机、描述内地址/专线号 同步虚拟
const STATIC_ORDERS = [
  { id: 's5', no: 'WO-20261022-1968', customer: '某集团公司', time: '10-22 06:25:41｜用时154分钟',
    title: 'ot.s5', productNo: '30122046287',
    desc: 'od.s5',
    city: '广州市', district: '翠湖区' },
  { id: 's1', no: 'WO-20261020-3417', customer: '某银行', time: '10-20 01:55:05｜用时35分钟',
    title: 'ot.s1', productNo: '30122075634',
    desc: 'od.s1',
    city: '广州市', district: '麓川区' },
  { id: 's2', no: 'WO-20261018-9065', customer: '某系统集成公司', time: '10-18 01:55:39｜用时175分钟',
    title: 'ot.s2', productNo: '30122037695',
    desc: 'od.s2',
    city: '广州市', district: '榕江区' },
  { id: 's4', no: 'WO-20261012-4827', customer: '某储能科技公司', time: '10-12 10:49:30｜用时145分钟',
    title: 'ot.s4', productNo: '30122059831',
    desc: 'od.s4',
    city: '广州市', district: '白泽区' },
  { id: 's3', no: 'WO-20261009-7531', customer: '某银行深圳分行', time: '10-09 14:54:56｜用时140分钟',
    title: 'ot.s3', productNo: '20221308465',
    desc: 'od.s3',
    city: '深圳市', district: '鹏南区' },
];

// V6.40/41：静态卡展开详情数据（用户提供——地市随单，V6.75 起统一 ***；不与投诉识别
// 面板/案例数据同源：静态工单无右侧拓扑故事线承载）
// V6.43（用户规格）：头部第一行改为【工单标题】；集团编号→产品编号；故障地点→投诉时间
// V6.44（用户规格）：标题/产品编码按《故事线工单详情》补全；投诉时间为全文年月日格式
const staticDetailData = (o) => ({
  title: o.title,
  desc: o.desc,
  // V6.66：全表单化——标题/描述改信息行，信息行去重（集团名称/时间在表单）
  area: [
    { label: 'om.city', value: o.city },
    { label: 'om.district', value: o.district },
    { label: 'om.product', value: o.productNo },
  ],
});

// V6.63..V6.66（用户规格）：工单详情弹窗数据——真卡/静态卡统一；V6.66 全表单化：
// 投诉单号 第一行、工单标题 第二行（值去【】）、投诉信息 第三行、
// 集团名称/投诉时间/归属地市/归属区县/产品编号 随后、状态 末行；
// V6.72（用户规格）：删除「工单耗时」行（耗时仍见卡面受理时间行）
function modalData(id, pub) {
  const clean = (t) => t.replace(/[【】]/g, ' ').replace(/\s+/g, ' ').trim();
  const build = (no, d, customer, status, time) => {
    const [date] = time.split('｜');
    return {
      rows: [
        { label: 'om.no', value: no },
        { label: 'om.titleLbl', value: clean(T(d.title)) },
        { label: 'om.info', value: d.desc },
        { label: 'om.customer', value: customer },
        { label: 'om.time', value: '2026-' + date },
        ...d.area,
        { label: 'om.status', value: status },
      ],
    };
  };
  if (id === 'c1' || id === 'c2') {
    const k = id;
    const playing = !pub.world ? false : !pub.world.caseDone;
    const status = pub.caseId === k && playing ? '回放中' : '已完成';
    return { detail: build(CASES[k].orderNo, orderDetailData(k), CASES[k].customer, status, TIMES[k]) };
  }
  const o = STATIC_ORDERS.find((s) => s.id === id);
  return { detail: build(o.no, staticDetailData(o), o.customer, '已完成', o.time) };
}

// V6.63（用户规格）：工单详情弹窗——全屏遮罩（点击关闭）+ 居中玻璃面板（右上 × 关闭）；
// V6.65/V6.66（用户规格）：单一表单（信息行全量表）——无标题头/描述段/图标
function WorkOrderModal({ data, onClose }) {
  return (
    <div className="wom-backdrop" onClick={onClose}>
      <div className="wom glass-panel" onClick={(e) => e.stopPropagation()}>
        <div className="fp-head">
          <div className="p-title-bar" />
          <div className="p-title-text">{T('om.title')}</div>
          <button className="wom-close" onClick={onClose} title={T('om.close')} aria-label={T('om.close')}>
            <svg width="0.625rem" height="0.625rem" viewBox="0 0 10 10" aria-hidden="true">
              <path d="M1.5 1.5 L8.5 8.5 M8.5 1.5 L1.5 8.5" fill="none" stroke="rgba(201,201,201,1)" strokeWidth="1.4" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="wom-body">
          <WorkOrderDetailPanel rows={data.detail.rows} />
        </div>
      </div>
    </div>
  );
}

function StaticOrderCard({ o, pub, expanded }) {
  return (
    <div className="fl-order fl-order--static" style={{ border: '1px solid rgba(119,119,119,1)' }}>
      <div className="fl-order__no">{o.no}</div>
      <div className="fl-order__row">
        <img src="/icons/ic_ebg_hospital.svg" alt="" draggable={false} />
        <span className="fl-order__cust" title={T(o.customer)}>{T(o.customer)}</span>
        <span className="fl-order__pill" style={{ background: 'rgba(9,170,113,0.15)', color: 'rgba(54,193,141,1)' }}>{T('lp.done')}</span>
      </div>
      <div className="fl-order__last">
        <span className="fl-order__time">{T(o.time)}</span>
        {/* V6.63（用户规格）：详情按钮——弹窗呈现（无角标图标）；
            与真卡共用 orderDetail 单开互斥；卡体仍不可点击（不选中/不切案） */}
        <span
          className={'fl-order__detail' + (expanded ? ' fl-order__detail--open' : '')}
          onClick={(e) => { e.stopPropagation(); pub.api.setOrderDetail(expanded ? null : o.id); }}
        >
          {T('om.details')}
        </span>
      </div>
    </div>
  );
}

export default function OrderPanel({ pub }) {
  if (pub.ordersHidden) return null;
  return (
    <>
      {/* V6.2（用户规格）：工单列表收起把手——设计 boder/箭头（23:137098/I23:137099）隐藏，
          本组件重建（12×48 @ 304,492，右圆角贴面板右缘；图标参考日志面板把手箭头样式，
          左指 = 收起方向）；点击收起（收起态由 PanelHandles 左缘把手展开） */}
      <button className="fl-ordertab" onClick={pub.api.toggleOrders}
        title={T('order.collapse')} aria-label={T('order.collapse')}>
        <Chevron />
      </button>
      <div className="fl-orders" style={{ left: ORDERS.c1.box.x, top: ORDERS.c1.box.y }}>
        {/* V6.6（用户规格）：两案位置对调——第一张卡片展示 case2、第二张展示 case1
             （选中态/角标/回放中胶囊/过滤/点击切换按案例挂卡，随渲染序自动落位）；
             V6.63（用户规格）：「展开」内嵌详情面板废止——详情按钮弹窗呈现
             （WorkOrderModal，卡内容+详情内容合并；真卡/静态卡单开互斥） */}
        {['c2', 'c1'].filter((k) => orderVisible(k, pub)).map((k) => {
          const bc = pub.caseId === k ? 'rgba(46,134,222,1)' : 'rgba(119,119,119,1)';
          return <OrderCard key={k} k={k} pub={pub} bc={bc} />;
        })}
        {/* V6.37/40（用户规格）：静态展示工单卡×4（两卡下方，卡体不可点击；
            详情按钮可点——弹窗与真卡单开互斥） */}
        {STATIC_ORDERS.map((o) => (
          <StaticOrderCard key={o.no} o={o} pub={pub} expanded={pub.orderDetail === o.id} />
        ))}
      </div>
      {/* V6.63（用户规格）：工单详情弹窗——全屏遮罩 + 居中玻璃面板（最高层 z100）；
          遮罩点击 / 右上 × / 再点详情按钮 关闭 */}
      {pub.orderDetail ? (
        <WorkOrderModal data={modalData(pub.orderDetail, pub)} onClose={() => pub.api.setOrderDetail(null)} />
      ) : null}
    </>
  );
}
