/* Server is the authority for JST epochs; browser timezone is not used. */
(() => {
  const state = {period_id: null, known: false};
  let pending = null, timer = null;
  function render(data) {
    const panel = document.getElementById('rotation-status');
    if (!panel) return;
    panel.textContent = data.rotation_enabled
      ? '鍵付き自動更新: '+({daily:'日次',weekly:'週次',monthly:'月次'})[data.cadence]
        +' / 期間 '+data.period_id+'\n次回: '+data.next_update_jst.replace('T',' ')
        +' JST / 鍵識別子 '+data.key_id
      : '自動更新: OFF（鍵なしの固定変換）';
  }
  async function refresh() {
    if (pending) return pending;
    pending = (async () => {
      try {
        const response = await fetch('/api/rotation');
        const data = await response.json();
        if (!response.ok) throw Error(data.error || '更新状態を取得できませんでした。');
        const changed = !state.known || state.period_id !== data.period_id || state.key_id !== data.key_id;
        Object.assign(state, data, {known: true});
        render(data);
        if (changed) window.dispatchEvent(new Event('hacs-period-change'));
        clearTimeout(timer);
        const seconds = data.seconds_until_update;
        timer = setTimeout(() => refresh().catch(() => {}), seconds === null ? 15000 : Math.max(500, Math.min(15000, seconds*1000+100)));
        return data;
      } catch (error) {
        state.known = false;
        const panel = document.getElementById('rotation-status');
        if (panel) panel.textContent = '更新状態を確認できません: '+error.message;
        window.dispatchEvent(new Event('hacs-period-change'));
        clearTimeout(timer); timer = setTimeout(() => refresh().catch(() => {}), 15000);
        throw error;
      } finally { pending = null; }
    })();
    return pending;
  }
  window.hacsRotation = {
    state,
    refresh,
    async assertPeriod(identifier, duration=0, expectedKey=null) {
      const current = await refresh();
      if (identifier !== (current.period_id || ''))
        throw Error('期間が更新されました。現在のコードで音声を再生成してください。');
      if (expectedKey !== null && expectedKey !== (current.key_id || ''))
        throw Error('共通鍵が更新されました。音声を再生成してください。');
      if (current.rotation_enabled && current.seconds_until_update < duration+.25)
        throw Error('更新直前です。更新後に音声を再生成してください。');
      return current;
    }
  };
  document.addEventListener('visibilitychange', () => {if (!document.hidden) refresh().catch(() => {});});
  document.addEventListener('DOMContentLoaded', () => refresh().catch(() => {}));
})();
