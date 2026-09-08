/**
 * timeline.js - 使用時刻（タイムライン）画面
 *
 * 1日を24時間の円環で表す。0時を上として時計回りに進み、使用した区間を弧で描く。
 * 弧は一律の色で「使っていた／いなかった」だけを示し、どのアプリかは
 * マウスを重ねたときの中央表示と、凡例を選んだときの強調で見分ける。
 */

const SECONDS_PER_DAY = 24 * 60 * 60;

// 円環の寸法（viewBox 200x200 上の値）
// 枠の大きさに対して円が小さく見えないよう、外周いっぱいまで使う
// （外径は radius + width/2 = 83 で、枠の 83%）
const RING = {
    center: 100,
    radius: 74,
    width: 18,
    labelRadius: 94,
    tickInner: 85,
    tickOuter: 89,
};
const CIRCUMFERENCE = 2 * Math.PI * RING.radius;
// 短い区間でも見えるようにする最小の弧長
const MIN_ARC = 1.5;

/** 使用した区間はアプリを問わず同じ色にする。値は style.css から読む */
const usedColor = () => theme.color('--bar-1');
const SVG_NS = 'http://www.w3.org/2000/svg';

const state = {
    date: '',
    sessions: [],
    totals: [],
    summary: null,
    // 凡例で選んだアプリ（選択中はその区間だけを強調する）
    selectedApp: null,
};

const nodes = {
    title: document.getElementById('timelineTitle'),
    summary: document.getElementById('timelineSummary'),
    ring: document.getElementById('ring'),
    legend: document.getElementById('legend'),
    daySummary: document.getElementById('daySummary'),
    sessionList: document.getElementById('sessionList'),
    sessionHeading: document.getElementById('sessionHeading'),
};

// 中央に表示する文字（描画のたびに作り直す）
let centerMain = null;
let centerSub = null;
let centerNote = null;

// ── ユーティリティ ──

const utils = {
    /** 0時を上とした、指定時刻の座標 */
    pointAt(hour, radius) {
        const angle = (hour / 24) * 2 * Math.PI - Math.PI / 2;
        return {
            x: RING.center + radius * Math.cos(angle),
            y: RING.center + radius * Math.sin(angle),
        };
    },
};

/** 属性を指定してSVG要素を作る */
function createElement(name, attributes) {
    const element = document.createElementNS(SVG_NS, name);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
    return element;
}

// ── 描画 ──

const ui = {
    renderRing() {
        const svg = createElement('svg', { viewBox: '0 0 200 200', class: 'ring-svg' });

        svg.appendChild(this.createTrack());
        this.createTicks().forEach((tick) => svg.appendChild(tick));
        this.createHourLabels().forEach((label) => svg.appendChild(label));

        // 0時を上にするため、円の開始位置を90度戻す
        const arcs = createElement('g', { transform: `rotate(-90 ${RING.center} ${RING.center})` });
        state.sessions.forEach((session) => arcs.appendChild(this.createArc(session)));
        svg.appendChild(arcs);

        this.createCenterText().forEach((text) => svg.appendChild(text));

        nodes.ring.replaceChildren(svg);
        this.showTotals();
    },

    createTrack() {
        return createElement('circle', {
            cx: RING.center,
            cy: RING.center,
            r: RING.radius,
            fill: 'none',
            stroke: theme.color('--bg-active'),
            'stroke-width': RING.width,
        });
    },

    /** 3時間ごとの目盛り */
    createTicks() {
        const ticks = [];
        for (let hour = 0; hour < 24; hour += 3) {
            const inner = utils.pointAt(hour, RING.tickInner);
            const outer = utils.pointAt(hour, RING.tickOuter);
            ticks.push(
                createElement('line', {
                    x1: inner.x,
                    y1: inner.y,
                    x2: outer.x,
                    y2: outer.y,
                    stroke: theme.color('--border'),
                    'stroke-width': 1,
                })
            );
        }
        return ticks;
    },

    createHourLabels() {
        return [0, 6, 12, 18].map((hour) => {
            const point = utils.pointAt(hour, RING.labelRadius);
            const label = createElement('text', {
                x: point.x,
                y: point.y + 3,
                'text-anchor': 'middle',
                class: 'ring-hour',
            });
            label.textContent = String(hour);
            return label;
        });
    },

    /** 使用区間1つ分の弧 */
    createArc(session) {
        const length = Math.max((session.length / SECONDS_PER_DAY) * CIRCUMFERENCE, MIN_ARC);
        const offset = -(session.offset / SECONDS_PER_DAY) * CIRCUMFERENCE;

        const arc = createElement('circle', {
            cx: RING.center,
            cy: RING.center,
            r: RING.radius,
            fill: 'none',
            stroke: usedColor(),
            'stroke-width': RING.width,
            'stroke-dasharray': `${length} ${CIRCUMFERENCE - length}`,
            'stroke-dashoffset': offset,
            class: 'ring-arc',
        });

        // 詳細は中央へ出すため、値を持たせておく
        arc.dataset.app = session.app;
        arc.dataset.start = session.start;
        arc.dataset.end = session.end;
        arc.dataset.seconds = String(session.seconds);
        if (state.selectedApp) {
            // 選んだアプリは濃く、それ以外は薄くする
            arc.classList.add(session.app === state.selectedApp ? 'is-selected' : 'is-dimmed');
        }
        return arc;
    },

    createCenterText() {
        centerMain = createElement('text', {
            x: RING.center,
            y: RING.center - 2,
            'text-anchor': 'middle',
            class: 'ring-main',
        });
        centerSub = createElement('text', {
            x: RING.center,
            y: RING.center + 13,
            'text-anchor': 'middle',
            class: 'ring-sub',
        });
        centerNote = createElement('text', {
            x: RING.center,
            y: RING.center + 26,
            'text-anchor': 'middle',
            class: 'ring-sub',
        });
        return [centerMain, centerSub, centerNote];
    },

    /** 中央に1日の合計を表示する（通常時） */
    showTotals() {
        if (state.selectedApp) {
            const item = state.totals.find((t) => t.app === state.selectedApp);
            const count = state.sessions.filter((s) => s.app === state.selectedApp).length;
            centerMain.textContent = format.truncate(state.selectedApp, 12);
            centerSub.textContent = format.duration(item ? item.seconds : 0);
            centerNote.textContent = `${count}区間`;
            return;
        }

        if (state.sessions.length === 0) {
            centerMain.textContent = '記録なし';
            centerSub.textContent = '';
            centerNote.textContent = '';
            return;
        }

        const total = state.sessions.reduce((sum, session) => sum + session.seconds, 0);
        centerMain.textContent = format.duration(total);
        centerSub.textContent = `${state.totals.length}アプリ ・ ${state.sessions.length}区間`;
        centerNote.textContent = '';
    },

    /** 中央に、指している区間の詳細を表示する */
    showSession(arc) {
        centerMain.textContent = format.truncate(arc.dataset.app, 12);
        centerSub.textContent = `${arc.dataset.start}〜${arc.dataset.end}`;
        centerNote.textContent = format.duration(Number(arc.dataset.seconds));
    },

    /** 使用時間の長い順に、アプリを縦に並べる */
    renderLegend() {
        nodes.legend.replaceChildren();

        state.totals.forEach((item) => {
            const row = document.createElement('button');
            row.type = 'button';
            row.className = 'legend-item';
            row.dataset.app = item.app;
            if (state.selectedApp === item.app) row.classList.add('active');

            const swatch = document.createElement('span');
            swatch.className = 'legend-swatch';
            swatch.style.background = usedColor();

            const name = document.createElement('span');
            name.className = 'legend-name';
            name.textContent = item.app;
            name.title = item.app;
            // どの端末で使ったかを添える（端末が1つしか無い場合は付けない）
            (item.devices ?? []).forEach((device) => {
                if (!devices.hasMultiple) return;
                const tag = document.createElement('span');
                tag.className = 'device-tag';
                tag.textContent = devices.label(device);
                name.appendChild(tag);
            });

            const duration = document.createElement('span');
            duration.className = 'legend-duration';
            duration.textContent = format.duration(item.seconds);

            row.append(swatch, name, duration);
            nodes.legend.appendChild(row);
        });
    },

    renderSummary() {
        nodes.title.textContent = format.heading(state.date);
        nodes.summary.textContent = state.sessions.length ? '0時を上に時計回り' : '';
    },

    /** その日の要約（開始・終了・最長・前日比） */
    renderDayStats() {
        nodes.daySummary.replaceChildren();
        const summary = state.summary;
        if (!summary || !summary.start) return;

        const longest = summary.longest;
        const stats = [
            ['開始', summary.start],
            ['終了', summary.end],
            ['最長の区間', format.duration(longest.seconds)],
            ['前日比', format.diff(summary.diff)],
        ];

        stats.forEach(([label, value], index) => {
            const cell = document.createElement('div');
            cell.className = 'day-stat';

            const caption = document.createElement('span');
            caption.className = 'day-stat-label';
            caption.textContent = label;

            const text = document.createElement('span');
            text.className = 'day-stat-value';
            text.textContent = value;
            // 最長の区間は、どのアプリだったかを補足する
            if (index === 2) text.title = `${longest.app} ${longest.start}〜${longest.end}`;

            cell.append(caption, text);
            nodes.daySummary.appendChild(cell);
        });
    },

    /** 区間の一覧（時刻順） */
    renderSessionList() {
        nodes.sessionList.replaceChildren();
        // 見出しはスクロール領域の外にあるため、表示だけを切り替える
        nodes.sessionHeading.hidden = state.sessions.length === 0;
        if (state.sessions.length === 0) return;

        state.sessions.forEach((session) => {
            const row = document.createElement('div');
            row.className = 'session-row';
            // 選択中のアプリ以外は控えめに表示する
            if (state.selectedApp && session.app !== state.selectedApp) {
                row.classList.add('is-dimmed');
            }

            const time = document.createElement('span');
            time.className = 'session-time';
            time.textContent = `${session.start}〜${session.end}`;

            const name = document.createElement('span');
            name.className = 'session-app';
            name.textContent = session.app;
            name.title = session.app;
            if (session.device && devices.hasMultiple) {
                const tag = document.createElement('span');
                tag.className = 'device-tag';
                tag.textContent = devices.label(session.device);
                name.appendChild(tag);
            }

            const duration = document.createElement('span');
            duration.className = 'session-duration';
            duration.textContent = format.duration(session.seconds);

            row.append(time, name, duration);
            nodes.sessionList.appendChild(row);
        });
    },
};

// ── 操作 ──

const actions = {
    async load(date) {
        const data = await api.get(`/api/timeline?date=${encodeURIComponent(date)}`);
        if (!data) {
            nodes.title.textContent = '読み込めませんでした';
            return;
        }

        state.date = data.date;
        state.sessions = data.sessions;
        state.totals = data.totals;
        state.summary = data.summary;
        // 日付を変えたら絞り込みは解除する
        state.selectedApp = null;
        dateBar.set(data.date);

        ui.renderSummary();
        ui.renderRing();
        ui.renderDayStats();
        ui.renderLegend();
        ui.renderSessionList();
    },

    /** 凡例で選んだアプリだけを強調する（同じものを再度押すと解除） */
    selectApp(app) {
        state.selectedApp = state.selectedApp === app ? null : app;
        ui.renderRing();
        ui.renderLegend();
        ui.renderSessionList();
    },

};

// ── 初期化 ──

function setupEvents() {
    nodes.legend.addEventListener('click', (event) => {
        const row = event.target.closest('.legend-item');
        if (row) actions.selectApp(row.dataset.app);
    });

    // 弧を指している間だけ、中央の表示を詳細に差し替える
    nodes.ring.addEventListener('mouseover', (event) => {
        const arc = event.target.closest('.ring-arc');
        if (arc) ui.showSession(arc);
    });
    nodes.ring.addEventListener('mouseout', (event) => {
        if (event.target.closest('.ring-arc')) ui.showTotals();
    });
}

async function init() {
    setupEvents();
    // 端末の表示名は状態と一緒に取り込むため、先に済ませてから描画する
    statusBar.init();
    await statusBar.refresh();
    dateBar.init((date) => actions.load(date));
    actions.load(dateBar.initialDate());
}

init();
