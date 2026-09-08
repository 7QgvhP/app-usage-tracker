/**
 * history.js - 履歴（過去の利用状況）画面
 *
 * 縦に日付、横に24時間を取り、1時間ごとの使用量を濃さで表す。
 * 日付をクリックすると、その日のタイムラインへ移動する。
 */

// 1時間あたりの使用量を5段階へ分ける境目（秒）
const LEVEL_THRESHOLDS = [0, 15 * 60, 30 * 60, 45 * 60];
const AXIS_HOURS = [0, 6, 12, 18];

// 画面の高さに合わせて自動調整する範囲
const CELL_MIN = 10;
const CELL_MAX = 34;
// セルの縦横比の上限（横幅の何倍まで縦に伸ばすか）
const CELL_ASPECT = 1.3;
const GAP_MIN = 2;
const GAP_MAX = 12;
// セクションとページの下余白のぶん
const PADDING_ALLOWANCE = 64;
// 収まる高さを探すときの試行回数（数回で収束する）
const FIT_ATTEMPTS = 6;
// 縮めても収まらない画面で用いる、読みやすさを保てる高さ
const COMFORTABLE_CELL_HEIGHT = 18;

// 表示する期間（切り替えはせず固定）
const HISTORY_DAYS = 30;

const state = {
    rows: [],
    // 絞り込み中のアプリ（空ならすべて）
    app: '',
};

const nodes = {
    title: document.getElementById('historyTitle'),
    note: document.getElementById('historyNote'),
    heatmap: document.getElementById('heatmap'),
    appFilter: document.getElementById('appFilter'),
};

// ── ユーティリティ ──

const utils = {
    /** 使用秒数を0〜4の濃さへ変換する */
    level(seconds) {
        if (seconds <= LEVEL_THRESHOLDS[0]) return 0;
        if (seconds <= LEVEL_THRESHOLDS[1]) return 1;
        if (seconds <= LEVEL_THRESHOLDS[2]) return 2;
        if (seconds <= LEVEL_THRESHOLDS[3]) return 3;
        return 4;
    },
};

// ── 描画 ──

const ui = {
    render() {
        nodes.heatmap.replaceChildren();

        if (state.rows.every((row) => row.total === 0)) {
            const empty = document.createElement('div');
            empty.className = 'empty-state';
            empty.textContent = state.app
                ? `${state.app} はこの期間に使われていません`
                : 'この期間の記録はありません';
            nodes.heatmap.appendChild(empty);
            return;
        }

        state.rows.forEach((row) => nodes.heatmap.appendChild(this.createRow(row)));
        nodes.heatmap.appendChild(this.createAxis());
        this.fitToViewport();
    },

    /** 行数に応じてセルの高さと行間を決め、画面の高さを使い切る */
    fitToViewport() {
        const cells = nodes.heatmap.querySelector('.heat-cells');
        const rows = state.rows.length;
        if (!cells || rows === 0) return;

        // 自身の位置から求めると中央寄せの結果と影響し合い、
        // セクションの高さから求めると内容が伸びた分だけ増えてしまう。
        // そのため、位置が動かないセクション上端と画面の高さを基準にする
        const section = nodes.heatmap.closest('.section');
        const header = section.querySelector('.section-header');
        const legend = section.querySelector('.heat-legend');
        const sectionTop = section.getBoundingClientRect().top + window.scrollY;
        const available =
            window.innerHeight - sectionTop - PADDING_ALLOWANCE
            - header.offsetHeight - legend.offsetHeight;

        const style = document.documentElement.style;
        const apply = (cell, gap) => {
            style.setProperty('--heat-cell-height', `${cell}px`);
            style.setProperty('--heat-row-gap', `${gap}px`);
            return nodes.heatmap.getBoundingClientRect().height;
        };

        // 縦に間延びしないよう、セルの横幅を基準に上限を決める
        const cellWidth = cells.getBoundingClientRect().width / 24;
        const limit = Math.min(CELL_MAX, Math.max(CELL_MIN, Math.round(cellWidth * CELL_ASPECT)));

        // セル以外の余白はCSS側で決まるうえ、セルを小さくすると
        // 行の高さが日付の文字で決まるようになり、単純な比例にならない。
        // そのため実際に描いた高さを見ながら、収まるまで縮める
        let height = limit;
        let actual = apply(height, GAP_MIN);
        for (let i = 0; i < FIT_ATTEMPTS && actual > available; i++) {
            const next = Math.max(CELL_MIN, height - Math.ceil((actual - available) / rows));
            if (next === height) break;   // これ以上小さくしても縮まない
            height = next;
            actual = apply(height, GAP_MIN);
        }

        // 縮めても収まらない画面では、読みにくい大きさにするより
        // 適度な高さのままスクロールさせる
        if (actual > available && height < COMFORTABLE_CELL_HEIGHT) {
            height = COMFORTABLE_CELL_HEIGHT;
            actual = apply(height, GAP_MIN);
        }

        // セルだけで埋まらない分は行間へ回す
        const spare = available - actual;
        const extra = spare > 0 && rows > 1 ? Math.floor(spare / (rows - 1)) : 0;
        apply(height, Math.min(GAP_MAX, GAP_MIN + extra));
    },

    createRow(row) {
        const link = document.createElement('a');
        link.className = 'heat-row';
        // その日のタイムラインへ移動できるようにする
        link.href = `/timeline?date=${row.date}`;

        const label = document.createElement('span');
        label.className = 'heat-date';
        label.textContent = format.shortDate(row.date);

        const cells = document.createElement('span');
        cells.className = 'heat-cells';
        row.hours.forEach((seconds, hour) => {
            const cell = document.createElement('span');
            cell.className = 'heat-cell';
            cell.dataset.level = String(utils.level(seconds));
            cell.title = `${format.shortDate(row.date)} ${hour}時台　${format.duration(seconds)}`;
            cells.appendChild(cell);
        });

        const total = document.createElement('span');
        total.className = 'heat-total';
        total.textContent = row.total > 0 ? format.duration(row.total) : '—';

        link.append(label, cells, total);
        return link;
    },

    /** 時刻の目盛り（セルの列に合わせる） */
    createAxis() {
        const axis = document.createElement('div');
        axis.className = 'heat-axis';

        axis.appendChild(document.createElement('span'));

        const ticks = document.createElement('span');
        ticks.className = 'heat-ticks';
        AXIS_HOURS.forEach((hour) => {
            const tick = document.createElement('span');
            tick.style.left = `${(hour / 24) * 100}%`;
            tick.textContent = String(hour);
            ticks.appendChild(tick);
        });

        axis.append(ticks, document.createElement('span'));
        return axis;
    },

    /** 選べるアプリの一覧を作る（選択中の項目は保つ） */
    updateAppFilter(apps) {
        if (!nodes.appFilter || !apps) return;

        // アプリ名は記録された文字列をそのまま値にするため、DOMで組み立てる
        const makeOption = (value, label) => {
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            return option;
        };

        nodes.appFilter.replaceChildren(
            makeOption('', 'すべて'),
            ...apps.map((app) => makeOption(app, app)),
        );
        nodes.appFilter.value = state.app;
    },

    renderSummary() {
        const total = state.rows.reduce((sum, row) => sum + row.total, 0);
        const activeDays = state.rows.filter((row) => row.total > 0).length;
        nodes.title.textContent = `直近${HISTORY_DAYS}日間`;
        // 濃さの意味は左下の凡例が示すため、ここでは繰り返さない
        const scope = state.app ? `${state.app} ・ ` : '';
        nodes.note.textContent = activeDays
            ? `${scope}合計 ${format.duration(total)} ・ 記録のある日 ${activeDays}日`
            : `${scope}この期間の記録はありません`;
    },
};

// ── 操作 ──

const actions = {
    async load() {
        const query = state.app ? `?app=${encodeURIComponent(state.app)}` : '';
        const data = await api.get(`/api/history${query}`);
        if (!data) {
            nodes.title.textContent = '読み込めませんでした';
            return;
        }

        state.rows = data.rows;
        ui.updateAppFilter(data.apps);

        ui.renderSummary();
        ui.render();
    },

    selectApp(app) {
        state.app = app;
        this.load();
    },
};

// ── 初期化 ──

function setupEvents() {
    // ウィンドウの大きさが変わったら、セルの高さを合わせ直す
    window.addEventListener('resize', () => ui.fitToViewport());

    nodes.appFilter?.addEventListener('change', () => actions.selectApp(nodes.appFilter.value));
}

function init() {
    setupEvents();
    statusBar.init();
    actions.load();
}

init();
