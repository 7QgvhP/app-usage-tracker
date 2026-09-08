/**
 * common.js - 3画面で共通に使う表示の整形
 *
 * 同じ処理を画面ごとに持つと、片方だけ直したときに表記がずれる。
 * 時間・日付・端末名の見せ方はここへ集約する。
 *
 * 他のスクリプトより先に読み込むこと（defer の順序で保証している）。
 */

const format = {
    /**
     * 秒数を「2時間30分」の形へ整形する
     *
     * 1分に満たない場合は「1分未満」と表す。
     * 「0分」では使ったのかどうか分からないため。
     */
    duration(seconds) {
        if (seconds > 0 && seconds < 60) return '1分未満';
        return this.minutes(Math.floor(seconds / 60));
    },

    /** 分を「2時間30分」の形へ整形する（グラフの目盛りや制限時間にも使う） */
    minutes(value) {
        if (value < 60) return `${value}分`;
        const hours = Math.floor(value / 60);
        const rest = value % 60;
        return rest > 0 ? `${hours}時間${rest}分` : `${hours}時間`;
    },

    /** 前日との差を「+38分」「-1時間5分」の形へ */
    diff(seconds) {
        if (Math.abs(seconds) < 60) return '±0分';
        return (seconds > 0 ? '+' : '-') + this.duration(Math.abs(seconds));
    },

    /** YYYY-MM-DD を「2026年8月26日（水）」へ（見出し用） */
    heading(dateString) {
        const { y, m, d, weekday } = this._parse(dateString);
        return `${y}年${m}月${d}日（${weekday}）`;
    },

    /** YYYY-MM-DD を「8/26（水）」へ（一覧用の短い表記） */
    shortDate(dateString) {
        const { m, d, weekday } = this._parse(dateString);
        return `${m}/${d}（${weekday}）`;
    },

    /**
     * 期間を見出し用の表記へ
     *
     * 日「2026年8月26日（水）」／週「8月24日〜8月26日」／月「2026年8月」。
     * 3画面とも見出しには対象期間を出すため、ここで表記を揃える。
     */
    period(kind, start, end) {
        if (kind === 'day') return this.heading(end);
        if (kind === 'month') {
            const { y, m } = this._parse(end);
            return `${y}年${m}月`;
        }
        const from = this._parse(start);
        const to = this._parse(end);
        return `${from.m}月${from.d}日〜${to.m}月${to.d}日`;
    },

    /** Date を YYYY-MM-DD へ */
    toDateString(date) {
        const pad = (n) => String(n).padStart(2, '0');
        return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
    },

    /** YYYY-MM-DD を日数分ずらす */
    shiftDate(dateString, days) {
        const { y, m, d } = this._parse(dateString);
        return this.toDateString(new Date(y, m - 1, d + days));
    },

    /** 長い文字列を省略する */
    truncate(text, length) {
        return text.length <= length ? text : `${text.slice(0, length)}…`;
    },

    _parse(dateString) {
        const [y, m, d] = dateString.split('-').map(Number);
        return { y, m, d, weekday: '日月火水木金土'[new Date(y, m - 1, d).getDay()] };
    },
};

/**
 * 端末名を画面用の表記へ変換する
 *
 * 対応表は /api/status から受け取り、ここへ預ける。
 * 未登録の端末は記録された名前をそのまま使う。
 */
/**
 * 配色の取得。style.css の :root に定義した変数を唯一の出所とする
 *
 * JavaScript 側にも色を書くと、CSSと二重に管理することになり必ずずれる。
 * canvas や SVG のように CSS 変数を直接書けない場所へは、ここから渡す。
 */
const theme = {
    _cache: {},

    /** CSS変数の値を返す（例: theme.color('--bar-1')） */
    color(name) {
        if (!(name in this._cache)) {
            this._cache[name] = getComputedStyle(document.documentElement)
                .getPropertyValue(name)
                .trim();
        }
        return this._cache[name];
    },

    /** 連番の変数をまとめて返す（例: theme.scale('--bar-', 6)） */
    scale(prefix, count) {
        return Array.from({ length: count }, (_, i) => this.color(`${prefix}${i + 1}`));
    },
};

const devices = {
    labels: {},
    local: 'pc',

    apply(status) {
        this.labels = status?.devices ?? {};
        this.local = status?.local_device ?? 'pc';
    },

    label(device) {
        return this.labels[device] ?? device;
    },

    /** 端末が2つ以上記録されているか（1つなら端末名を出す意味がない） */
    get hasMultiple() {
        return Object.keys(this.labels).length > 1;
    },
};

/** API 呼び出し。失敗しても例外を投げず null を返す（画面は前回の値を保つ） */
const api = {
    async request(url, options = {}) {
        try {
            const res = await fetch(url, options);
            const body = await res.json().catch(() => null);
            if (!res.ok) {
                console.error(`APIエラー ${res.status}: ${url}`, body);
                return null;
            }
            return body;
        } catch (e) {
            console.error(`API通信に失敗しました: ${url}`, e);
            return null;
        }
    },

    get(url) {
        return this.request(url);
    },

    post(url, data) {
        return this.request(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
    },

    delete(url) {
        return this.request(url, { method: 'DELETE' });
    },
};

/** 画面下に短い知らせを出す */
function showToast(message) {
    document.querySelector('.toast-msg')?.remove();

    const toast = document.createElement('div');
    toast.className = 'toast-msg';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

/**
 * ヘッダー右上の状態表示と操作
 *
 * 計測中かどうか、ミニウィンドウ、一時停止は画面によらず同じ意味を持つため、
 * 3画面で同じ部品を使う。状態の取得もここでまとめて行う。
 */
const statusBar = {
    // 状態を確認する間隔（ミリ秒）
    INTERVAL: 15000,

    nodes: {},
    paused: false,
    connected: true,
    miniWindow: { available: false, visible: false },
    // 端末ごとの受信状況（同期が無効なら空）
    sync: [],
    // 状態を取り込んだあとに呼ばれる（画面ごとの追加処理に使う）
    onUpdate: null,

    init(onUpdate = null) {
        this.nodes = {
            dot: document.getElementById('statusDot'),
            text: document.getElementById('statusText'),
            pause: document.getElementById('togglePauseBtn'),
            mini: document.getElementById('showMiniBtn'),
            warning: document.getElementById('syncWarning'),
        };
        if (!this.nodes.dot) return;   // 状態表示を置いていない画面

        this.onUpdate = onUpdate;
        this.nodes.pause.addEventListener('click', () => this.togglePause());
        this.nodes.mini.addEventListener('click', () => this.showMiniWindow());

        this.refresh();
        setInterval(() => this.refresh(), this.INTERVAL);
    },

    /** 状態を取り込む。応答が無い場合はアプリ本体が停止しているとみなす */
    async refresh() {
        const status = await api.get('/api/status');
        this.apply(status);
    },

    apply(status) {
        this.connected = status !== null;
        if (status) {
            this.paused = status.paused;
            this.miniWindow = status.mini_window ?? { available: false, visible: false };
            this.sync = status.sync ?? [];
            devices.apply(status);
        }
        this.render();
        this.onUpdate?.(status);
    },

    render() {
        const { dot, text, pause, mini } = this.nodes;
        if (!dot) return;

        this.renderWarning();

        // アプリ本体が停止している間は、操作できないボタンを隠して状態を明示する
        dot.classList.toggle('offline', !this.connected);
        text.parentElement.classList.toggle('offline', !this.connected);
        if (!this.connected) {
            dot.classList.remove('paused');
            text.textContent = 'アプリが停止しています';
            pause.hidden = true;
            mini.hidden = true;
            return;
        }

        dot.classList.toggle('paused', this.paused);
        text.textContent = this.paused ? '一時停止中' : '計測中';
        pause.hidden = false;
        pause.textContent = this.paused ? '再開' : '一時停止';

        // ミニウィンドウを扱えない構成（ブラウザのみでの利用など）ではボタンを隠す
        mini.hidden = !this.miniWindow.available;
        mini.textContent = this.miniWindow.visible ? 'ミニウィンドウ表示中' : 'ミニウィンドウ';
    },

    /**
     * 受信が途絶えている端末を知らせる
     *
     * スマホのOSは数日分しかイベントを保持しないため、気付かずにいると
     * その期間の記録が失われる。届いていない状態を見えるようにする。
     */
    renderWarning() {
        const el = this.nodes.warning;
        if (!el) return;

        const stale = this.connected ? this.sync.filter((s) => s.stale) : [];
        el.hidden = stale.length === 0;
        if (el.hidden) return;

        const names = stale.map((s) => devices.label(s.device));
        el.textContent = `${names.join('・')} 未同期`;

        const lines = stale.map((s) => {
            const label = devices.label(s.device);
            const days = Math.floor(s.elapsed_hours / 24);
            const elapsed = days >= 1 ? `${days}日前` : `${Math.floor(s.elapsed_hours)}時間前`;
            return `${label}: 最後の受信は ${s.last_seen}（${elapsed}）`;
        });
        lines.push('端末のアプリが動いているか確認してください。');
        lines.push('数日放置すると、その間の記録は取り戻せません。');
        el.title = lines.join('\n');
    },

    async togglePause() {
        const res = await api.post('/api/toggle-pause', {});
        if (!res) {
            showToast('状態の切り替えに失敗しました');
            return;
        }

        this.paused = res.paused;
        this.render();
        showToast(this.paused ? '一時停止しました' : '再開しました');
    },

    async showMiniWindow() {
        const res = await api.post('/api/mini-window/show', {});
        if (!res?.ok) {
            showToast('ミニウィンドウを表示できませんでした');
            return;
        }

        // 表示は本体側のメインスレッドが行うため、少し待ってから状態を確認する
        showToast(res.requested ? 'ミニウィンドウを表示しました' : 'すでに表示されています');
        setTimeout(() => this.refresh(), 1200);
    },
};

/**
 * ヘッダーの日付切り替え
 *
 * ダッシュボードとタイムラインで同じ操作を提供する。
 * 選んだ日付は画面ごとの読み込み処理へ渡す。
 */
const dateBar = {
    nodes: {},
    date: '',
    onChange: null,

    /** @param onChange 日付が変わったときに呼ばれる（date を受け取る） */
    init(onChange) {
        this.nodes = {
            picker: document.getElementById('datePicker'),
            prev: document.getElementById('prevDayBtn'),
            next: document.getElementById('nextDayBtn'),
            today: document.getElementById('todayBtn'),
        };
        if (!this.nodes.picker) return;   // 日付操作を置いていない画面

        this.onChange = onChange;
        this.nodes.prev.addEventListener('click', () => this.move(-1));
        this.nodes.next.addEventListener('click', () => this.move(1));
        this.nodes.today.addEventListener('click', () => this.select(format.toDateString(new Date())));
        this.nodes.picker.addEventListener('change', () => this.select(this.nodes.picker.value));
    },

    /** 表示中の日付を反映する（読み込み後に呼ぶ） */
    set(date) {
        this.date = date;
        if (this.nodes.picker) this.nodes.picker.value = date;
    },

    select(date) {
        if (!date) return;
        this.set(date);
        this.onChange?.(date);
    },

    move(days) {
        this.select(format.shiftDate(this.date, days));
    },

    /** 開いた時点で表示する日付（履歴から日付を指定して来た場合はその日） */
    initialDate() {
        return new URLSearchParams(location.search).get('date')
            || format.toDateString(new Date());
    },
};
