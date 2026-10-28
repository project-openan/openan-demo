// Copyright (c) 2026 Huawei Technologies Co., Ltd.
// All Rights Reserved.
//
// SPDX-License-Identifier: Apache-2.0

/** 3D view of the PSOP workflow (replaces the 2D swimlane as the default
 *  graph view): a left-to-right layered DAG rendered with 3d-force-graph.
 *  Nodes are colored per agent, light up live with the replay (pending /
 *  active glow / done) and carry sprite labels; edges emit directional
 *  particles once their target step is running. Orbit controls: drag to
 *  rotate, wheel to zoom; the scene slowly auto-rotates until the user
 *  grabs it. Falls back to the 2D swimlane when WebGL is unavailable. */
import React, { useEffect, useMemo, useRef, useState } from 'react';
import * as THREE from 'three';
import ForceGraph3D from '3d-force-graph';
import SpriteText from 'three-spritetext';
import { agentColor } from '../colors.js';
import WorkflowGraph from './WorkflowGraph.jsx';

/* Tailwind color keys → hex used by the 3D scene (matches colors.js) */
const HEX = {
    blue: '#3b82f6',
    indigo: '#6366f1',
    emerald: '#10b981',
    amber: '#f59e0b',
    violet: '#8b5cf6',
    rose: '#f43f5e',
    sky: '#0ea5e9',
    teal: '#14b8a6',
};
const hexOf = (key) => HEX[key] || '#71717a';
const STATUS_COLOR = { pending: '#52525b', active: '#60a5fa', done: '#10b981' };

class Graph3DErrorBoundary extends React.Component {
    constructor(props) { super(props); this.state = { failed: false }; }
    static getDerivedStateFromError() { return { failed: true }; }
    render() { return this.state.failed ? this.props.fallback : this.props.children; }
}

/** One node object: a sphere colored by agent/status + a sprite label. */
function nodeObject(node, pick) {
    const group = new THREE.Group();
    const base = hexOf(node.agentColor);
    const color = node.status === 'pending' ? '#3f3f46' : base;
    const size = node.status === 'active' ? 9 : (node.status === 'done' ? 7 : 5.5);
    const mesh = new THREE.Mesh(
        new THREE.SphereGeometry(size, 24, 24),
        new THREE.MeshLambertMaterial({
            color,
            emissive: node.status === 'active' ? base : (node.status === 'done' ? '#065f46' : '#000000'),
            emissiveIntensity: node.status === 'active' ? 0.9 : (node.status === 'done' ? 0.35 : 0),
            transparent: true,
            opacity: node.status === 'pending' ? 0.55 : 1,
        })
    );
    if (node.status === 'active') {
        const halo = new THREE.Mesh(
            new THREE.SphereGeometry(14, 24, 24),
            new THREE.MeshBasicMaterial({ color: base, transparent: true, opacity: 0.18 })
        );
        group.add(halo);
    }
    if (node.end) {
        mesh.material.color = new THREE.Color('#a1a1aa');
    }
    group.add(mesh);

    const label = new SpriteText(node.end ? 'END' : pick(node.short) || pick(node.name));
    label.color = node.status === 'pending' ? '#a1a1aa' : '#f4f4f5';
    label.textHeight = 6.5;
    label.fontWeight = '700';
    label.position.set(0, -14, 0);
    label.backgroundColor = 'rgba(9,9,11,0.55)';
    label.padding = 1.5;
    label.borderRadius = 2;
    group.add(label);
    return group;
}

const WorkflowGraph3D = ({ tr, pick, steps, agents, stepStatus }) => {
    const containerRef = useRef(null);
    const fgRef = useRef(null);
    const statusRef = useRef(stepStatus);
    const pickRef = useRef(pick);
    const [failed, setFailed] = useState(false);
    statusRef.current = stepStatus;
    pickRef.current = pick;

    /* Graph data: steps + an END cap, sequential links. Memoized so the
     * graph mounts once; live statuses are patched onto these objects. */
    const graphData = useMemo(() => {
        const colorById = Object.fromEntries(agents.map((a) => [a.id, a.color]));
        const nodes = steps.map((s) => ({
            id: s.id, name: s.name, short: s.short, agent: s.agent,
            agentColor: colorById[s.agent] || 'blue',
            status: stepStatus[s.id] || 'pending',
        }));
        if (steps.length) {
            const last = steps[steps.length - 1];
            nodes.push({
                id: '__end__', end: true, agent: last.agent,
                agentColor: colorById[last.agent] || 'blue',
                status: 'pending',
            });
        }
        const links = nodes.slice(0, -1).map((n, i) => ({
            source: n.id, target: nodes[i + 1].id,
            status: stepStatus[steps[i + 1]?.id] || 'pending',
        }));
        return { nodes, links };
    }, [steps, agents]); // eslint-disable-line react-hooks/exhaustive-deps

    /* Patch live statuses onto the mounted graph and refresh visuals. */
    useEffect(() => {
        const fg = fgRef.current;
        if (!fg) return;
        for (const n of graphData.nodes) n.status = n.end ? 'pending' : (stepStatus[n.id] || 'pending');
        for (const l of graphData.links) l.status = stepStatus[l.target?.id || l.target] || 'pending';
        fg.refresh();
    }, [stepStatus, graphData]);

    /* Mount the 3D scene once. */
    useEffect(() => {
        let disposed = false;
        let ro = null;
        const el = containerRef.current;
        if (!el) return undefined;
        try {
            const fg = ForceGraph3D()(el)
                .graphData(graphData)
                .backgroundColor('rgba(0,0,0,0)')
                .dagMode('lr')
                .dagLevelDistance(90)
                .nodeRelSize(4.5)
                .nodeLabel((n) => `${n.end ? 'END' : pickRef.current(n.name)} · ${n.agent || ''}`)
                .nodeThreeObject((n) => nodeObject(n, pickRef.current))
                .linkColor((l) => (l.status === 'done' ? '#10b981' : l.status === 'active' ? '#60a5fa' : '#3f3f46'))
                .linkWidth((l) => (l.status === 'active' ? 3 : l.status === 'done' ? 1.8 : 0.8))
                .linkOpacity(0.85)
                .linkDirectionalParticles((l) => (l.status === 'active' ? 5 : l.status === 'done' ? 2 : 0))
                .linkDirectionalParticleWidth((l) => (l.status === 'active' ? 3.4 : 2.2))
                .linkDirectionalParticleColor((l) => (l.status === 'active' ? '#93c5fd' : '#34d399'))
                .linkDirectionalParticleSpeed(0.012)
                .onEngineStop(() => {
                    try { fgRef.current?.zoomToFit(700, 60); } catch (e) { /* ignore */ }
                });
            fg.d3Force('charge')?.strength(-220);
            // gentle auto-rotate until the user grabs the scene
            try {
                const controls = fg.controls();
                controls.autoRotate = true;
                controls.autoRotateSpeed = 0.55;
                const stop = () => { controls.autoRotate = false; };
                controls.addEventListener('start', stop);
            } catch (e) { /* ignore */ }
            fgRef.current = fg;

            ro = new ResizeObserver(() => {
                if (disposed || !el.isConnected) return;
                try {
                    fg.width(el.clientWidth);
                    fg.height(el.clientHeight);
                } catch (e) { /* ignore */ }
            });
            ro.observe(el);

            return () => {
                disposed = true;
                if (ro) ro.disconnect();
                try { fg._destructor?.(); } catch (e) { /* ignore */ }
                el.innerHTML = '';
                fgRef.current = null;
            };
        } catch (e) {
            setFailed(true);
            return undefined;
        }
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    if (failed) {
        return <WorkflowGraph pick={pick} steps={steps} agents={agents} stepStatus={stepStatus} />;
    }

    return (
        <div className="relative h-full w-full">
            <div ref={containerRef} className="absolute inset-0" />
            {/* agent legend + interaction hint */}
            <div className="absolute left-2 top-2 z-10 flex flex-col gap-1 pointer-events-none">
                {agents.map((a) => (
                    <div key={a.id} className="flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-white/70 dark:bg-zinc-900/70 backdrop-blur-sm">
                        <span className="w-2 h-2 rounded-full shrink-0" style={{ background: hexOf(a.color) }} />
                        <span className="text-[11px] font-bold text-zinc-600 dark:text-zinc-300 leading-none">{pick(a.name)}</span>
                    </div>
                ))}
            </div>
            <div className="absolute right-2 bottom-2 z-10 pointer-events-none px-2 py-0.5 rounded-md bg-white/70 dark:bg-zinc-900/70 backdrop-blur-sm text-[11px] text-zinc-400 dark:text-zinc-500">
                {tr('ss.flow3d.hint', '拖拽旋转 · 滚轮缩放', 'Drag to rotate · Wheel to zoom')}
            </div>
        </div>
    );
};

export default function WorkflowGraph3DSafe(props) {
    return (
        <Graph3DErrorBoundary
            fallback={<WorkflowGraph pick={props.pick} steps={props.steps} agents={props.agents} stepStatus={props.stepStatus} />}
        >
            <WorkflowGraph3D {...props} />
        </Graph3DErrorBoundary>
    );
}
