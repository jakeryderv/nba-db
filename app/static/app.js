let season = null, teams = [], comparisonPlayers = [], shotPlayers = [], ready = false, activeSection = 'standings', shotGamesRequest = 0;
        const page = { players: {o:0,l:50,t:0}, games: {o:0,l:24,t:0} };
        const sections = new Set(['standings', 'leaders', 'games', 'shots', 'players', 'compare']);

        const HTML_ESCAPES = {'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'};

        // All API/database values must pass through this helper before insertion
        // into an HTML template. Event arguments are stored in escaped data
        // attributes and handled by the delegated click listener below.
        function h(value) {
            return String(value ?? '').replace(/[&<>"']/g, char => HTML_ESCAPES[char]);
        }

        function present(value, fallback = '-') {
            return value === null || value === undefined || value === '' ? fallback : value;
        }

        function pct(value) {
            const number = Number(value);
            return value === null || value === undefined || value === '' || !Number.isFinite(number)
                ? '-'
                : `${(number * 100).toFixed(1)}%`;
        }

        function showStatus(container, kind, message) {
            const status = document.createElement('div');
            status.className = kind;
            status.textContent = message;
            status.setAttribute('role', kind === 'error' ? 'alert' : 'status');
            container.replaceChildren(status);
        }

        function showLoading(container, subject) {
            showStatus(container, 'loading', `Loading ${subject}`);
        }

        function showError(container, subject, error) {
            showStatus(container, 'error', `Error loading ${subject}: ${error.message}`);
        }

        document.addEventListener('DOMContentLoaded', async () => {
            let searchTimeout;
            document.getElementById('player-search').oninput = () => {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(loadPlayers, 300);
            };
            document.getElementById('player-active').onchange = loadPlayers;
            document.getElementById('games-team').onchange = loadGames;
            document.getElementById('games-sort').onchange = loadGames;
            document.getElementById('leaders-stat').onchange = loadLeaders;
            document.getElementById('shot-subject-type').onchange = () => {
                populateShotSelectors();
                populateShotGames('');
            };
            document.getElementById('shot-subject').onchange = () => populateShotGames('');
            document.getElementById('shot-chart-form').onsubmit = event => {
                event.preventDefault();
                navigateShotChart();
            };
            document.getElementById('player-compare-form').onsubmit = event => {
                event.preventDefault();
                navigateComparison('players');
            };
            document.getElementById('team-compare-form').onsubmit = event => {
                event.preventDefault();
                navigateComparison('teams');
            };

            document.querySelectorAll('.modal-overlay').forEach(m => {
                m.onclick = e => { if(e.target === m) closeDetail(); };
            });
            document.onkeydown = e => {
                const modal = document.querySelector('.modal-overlay.active');
                if (!modal) return;
                if (e.key === 'Escape') {
                    closeDetail();
                    return;
                }
                if (e.key === 'Tab') trapDialogFocus(e, modal);
            };
            window.addEventListener('hashchange', route);

            document.addEventListener('click', e => {
                const target = e.target.closest('[data-action]');
                if (!target) return;
                const actions = {
                    paginate: () => paginate(target.dataset.key, Number(target.dataset.direction)),
                    'compare-tab': () => showCompareType(target.dataset.compareType),
                    'close-modal': () => closeDetail()
                };
                actions[target.dataset.action]?.();
            });

            try {
                const seasons = await api('/api/seasons');
                if (!seasons.length) throw new Error('No season is loaded');
                season = seasons[0].id;
                document.getElementById('season-label').textContent = `${season} Regular Season`;

                teams = await api('/api/teams');
                const teamSelect = document.getElementById('games-team');
                const allTeams = document.createElement('option');
                allTeams.value = '';
                allTeams.textContent = 'All Teams';
                teamSelect.replaceChildren(allTeams, ...teams.map(t => {
                    const option = document.createElement('option');
                    option.value = t.id;
                    option.textContent = t.full_name;
                    return option;
                }));

                comparisonPlayers = (await api('/api/players?active=true&limit=500')).data;
                shotPlayers = await api(`/api/shot-chart/players?${new URLSearchParams({season})}`);
                populateComparisonSelects();
                populateShotSelectors();
                populateShotOpponents();

                ready = true;
                if (!window.location.hash) history.replaceState(null, '', '#standings');
                route();
            } catch (error) {
                document.getElementById('season-label').textContent = 'Unavailable';
                showError(document.getElementById('standings-table'), 'application', error);
            }
        });

        async function api(url) {
            const r = await fetch(url);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            return r.json();
        }

        function parseRoute() {
            const [path, query = ''] = window.location.hash.slice(1).split('?');
            const [kind, ...parts] = path.split('/');
            return {
                kind: kind || 'standings',
                parts: parts.map(decodeURIComponent),
                filters: new URLSearchParams(query)
            };
        }

        async function route() {
            if (!ready) return;
            const {kind, parts, filters} = parseRoute();
            const id = parts[0] || null;
            if (kind === 'compare' && parts.length === 3 && ['players', 'teams'].includes(parts[0])) {
                activeSection = 'compare';
                closeModals();
                switchTo('compare', false);
                showCompareType(parts[0]);
                setComparisonSelection(parts[0], parts[1], parts[2]);
                loadComparison(parts[0], parts[1], parts[2]);
                return;
            }
            if (kind === 'shots' && parts.length >= 2 && ['player', 'team'].includes(parts[0])) {
                activeSection = 'shots';
                closeModals();
                switchTo('shots', false);
                setShotSelection(parts[0], parts[1], parts[2] || '');
                setShotFilters(filters);
                await populateShotGames(filters.get('game_id') || '');
                loadShotChart(parts[0], parts[1], parts[2] || '');
                return;
            }
            if (sections.has(kind)) {
                activeSection = kind;
                closeModals();
                switchTo(kind);
                return;
            }
            if (id && ({player: openPlayer, game: openGame, team: openTeam})[kind]) {
                ({player: openPlayer, game: openGame, team: openTeam})[kind](id);
                return;
            }
            history.replaceState(null, '', `#${activeSection}`);
            route();
        }

        function switchTo(s, load = true) {
            document.querySelectorAll('.nav-link').forEach(a => a.classList.toggle('active', a.dataset.section === s));
            document.querySelectorAll('.section').forEach(sec => sec.classList.toggle('active', sec.id === s));
            if (load) loadSection(s);
        }

        function loadSection(s) {
            s = s || document.querySelector('.nav-link.active').dataset.section;
            ({standings:loadStandings, leaders:loadLeaders, games:loadGames, shots:loadShots, players:loadPlayers, compare:loadCompare})[s]();
        }

        function populateComparisonSelects() {
            const fill = (id, rows, label) => {
                const select = document.getElementById(id);
                const prompt = document.createElement('option');
                prompt.value = '';
                prompt.textContent = `Select a ${label}`;
                select.replaceChildren(prompt, ...rows.map(row => {
                    const option = document.createElement('option');
                    option.value = row.id;
                    option.textContent = row.full_name;
                    return option;
                }));
            };
            ['compare-player-one', 'compare-player-two'].forEach(id => fill(id, comparisonPlayers, 'player'));
            ['compare-team-one', 'compare-team-two'].forEach(id => fill(id, teams, 'team'));
        }

        function showCompareType(type) {
            const playerMode = type !== 'teams';
            document.getElementById('player-compare-panel').hidden = !playerMode;
            document.getElementById('team-compare-panel').hidden = playerMode;
            document.querySelectorAll('.compare-tab').forEach(tab => {
                const selected = tab.dataset.compareType === (playerMode ? 'players' : 'teams');
                tab.classList.toggle('active', selected);
                tab.setAttribute('aria-selected', String(selected));
            });
        }

        function loadCompare() {
            showCompareType('players');
        }

        function populateShotSelectors() {
            const type = document.getElementById('shot-subject-type').value;
            const rows = type === 'team' ? teams : shotPlayers;
            const label = type === 'team' ? 'team' : 'player';
            const subject = document.getElementById('shot-subject');
            const comparison = document.getElementById('shot-compare-subject');
            const priorSubject = subject.value;
            const priorComparison = comparison.value;
            const options = rows.map(row => {
                const option = document.createElement('option');
                option.value = row.id;
                option.textContent = row.full_name;
                return option;
            });
            const prompt = document.createElement('option');
            prompt.value = '';
            prompt.textContent = `Select a ${label}`;
            subject.replaceChildren(prompt, ...options);
            if (rows.some(row => String(row.id) === priorSubject)) subject.value = priorSubject;

            const comparePrompt = document.createElement('option');
            comparePrompt.value = '';
            comparePrompt.textContent = 'No comparison';
            comparison.replaceChildren(comparePrompt, ...rows.map(row => {
                const option = document.createElement('option');
                option.value = row.id;
                option.textContent = row.full_name;
                return option;
            }));
            if (rows.some(row => String(row.id) === priorComparison)) comparison.value = priorComparison;
        }

        function populateShotOpponents() {
            const select = document.getElementById('shot-opponent');
            const prompt = document.createElement('option');
            prompt.value = '';
            prompt.textContent = 'All opponents';
            select.replaceChildren(prompt, ...teams.map(team => {
                const option = document.createElement('option');
                option.value = team.id;
                option.textContent = team.full_name;
                return option;
            }));
        }

        async function populateShotGames(selected = null) {
            const request = ++shotGamesRequest;
            const select = document.getElementById('shot-game');
            const type = document.getElementById('shot-subject-type').value;
            const id = document.getElementById('shot-subject').value;
            const prior = selected === null ? select.value : selected;
            const prompt = document.createElement('option');
            prompt.value = '';
            prompt.textContent = id ? 'Loading games…' : 'All games';
            select.replaceChildren(prompt);
            if (!id) return;

            try {
                const params = new URLSearchParams({season});
                params.set(type === 'player' ? 'player_id' : 'team_id', id);
                const games = await api(`/api/shot-chart/games?${params}`);
                if (request !== shotGamesRequest) return;
                prompt.textContent = 'All games';
                select.replaceChildren(prompt, ...games.map(game => {
                    const option = document.createElement('option');
                    option.value = game.id;
                    option.textContent = `${present(game.game_date, 'Date TBD')} · ${game.away_team} @ ${game.home_team}`;
                    return option;
                }));
                if (games.some(game => game.id === prior)) select.value = prior;
            } catch (error) {
                if (request !== shotGamesRequest) return;
                prompt.textContent = 'Games unavailable';
                select.replaceChildren(prompt);
            }
        }

        function loadShots() {
            const id = document.getElementById('shot-subject').value;
            if (id) loadShotChart(document.getElementById('shot-subject-type').value, id, document.getElementById('shot-compare-subject').value);
        }

        function navigateShotChart() {
            const type = document.getElementById('shot-subject-type').value;
            const id = document.getElementById('shot-subject').value;
            const comparison = document.getElementById('shot-compare-subject').value;
            const result = document.getElementById('shot-chart-result');
            if (!id || id === comparison) {
                showStatus(result, 'error', comparison ? 'Choose two distinct subjects.' : 'Choose a subject.');
                return;
            }
            const query = shotFilterParams();
            const routeValue = shotRoute(type, id, comparison, query);
            if (window.location.hash === routeValue) loadShotChart(type, id, comparison);
            else window.location.hash = routeValue;
        }

        function setShotSelection(type, id, comparison) {
            document.getElementById('shot-subject-type').value = type;
            populateShotSelectors();
            document.getElementById('shot-subject').value = id;
            document.getElementById('shot-compare-subject').value = comparison;
        }

        function setShotFilters(filters) {
            const controls = {
                opponent_id: 'shot-opponent',
                period: 'shot-period',
                made: 'shot-result',
                shot_type: 'shot-type'
            };
            Object.entries(controls).forEach(([key, control]) => {
                document.getElementById(control).value = filters.get(key) || '';
            });
        }

        function shotFilterParams() {
            const params = new URLSearchParams();
            const filters = {
                opponent_id: document.getElementById('shot-opponent').value,
                period: document.getElementById('shot-period').value,
                made: document.getElementById('shot-result').value,
                shot_type: document.getElementById('shot-type').value,
                game_id: document.getElementById('shot-game').value.trim()
            };
            Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, value); });
            return params;
        }

        function shotRoute(type, id, comparison = '', filters = new URLSearchParams()) {
            const path = `#shots/${encodeURIComponent(type)}/${encodeURIComponent(id)}${comparison ? `/${encodeURIComponent(comparison)}` : ''}`;
            const query = filters.toString();
            return `${path}${query ? `?${query}` : ''}`;
        }

        function contextualShotRoute(type, id, gameId, comparison = '') {
            return shotRoute(type, id, comparison, new URLSearchParams({game_id: gameId}));
        }

        function shotParams(type, id) {
            const params = shotFilterParams();
            params.set('season', season);
            params.set('max_points', '10000');
            params.set(type === 'player' ? 'player_id' : 'team_id', id);
            return params;
        }

        function subjectName(type, id) {
            const rows = type === 'team' ? teams : shotPlayers;
            return rows.find(row => String(row.id) === String(id))?.full_name || `${type} ${id}`;
        }

        async function loadShotChart(type, id, comparison = '') {
            const result = document.getElementById('shot-chart-result');
            showLoading(result, 'shot chart');
            try {
                const ids = comparison ? [id, comparison] : [id];
                const charts = await Promise.all(ids.map(value => api(`/api/shot-chart?${shotParams(type, value)}`)));
                const names = ids.map(value => subjectName(type, value));
                result.innerHTML = `
                    <div class="shot-summary-grid">${charts.map((chart, index) => `
                        <div class="shot-summary shot-series-${index + 1}">
                            <h3>${h(names[index])}</h3>
                            <strong>${h(chart.makes)} / ${h(chart.attempts)}</strong>
                            <span>${h(pct(chart.fg_pct))} FG · ${h(present(chart.points_per_shot))} points/shot${chart.fg_pct_vs_league === null ? '' : ` · ${h(percentagePoints(chart.fg_pct_vs_league))} vs league`}</span>
                        </div>`).join('')}</div>
                    ${charts.some(chart => chart.truncated) ? '<p class="shot-warning">The plotted points are capped for browser performance; zone totals remain complete.</p>' : ''}
                    <div class="shot-visual-grid">
                        ${shotCourt(charts, names)}
                        ${shotHeatmap(charts, names)}
                    </div>
                    ${shotZoneTable(charts, names)}`;
            } catch (error) {
                showError(result, 'shot chart', error);
            }
        }

        function shotCourt(charts, names) {
            const markers = charts.flatMap((chart, series) => chart.data.map(shot => {
                const x = Math.max(10, Math.min(510, Number(shot.loc_x) + 260));
                const y = Math.max(10, Math.min(500, 480 - Number(shot.loc_y)));
                const label = `${names[series]}: ${shot.shot_made ? 'Made' : 'Missed'} ${shot.action_type}, ${shot.shot_distance} ft, Q${shot.period} ${shot.minutes_remaining}:${String(shot.seconds_remaining).padStart(2, '0')}`;
                if (series === 0) return `<circle class="shot-marker shot-series-1 ${shot.shot_made ? 'made' : 'missed'}" cx="${h(x)}" cy="${h(y)}" r="4"><title>${h(label)}</title></circle>`;
                return `<rect class="shot-marker shot-series-2 ${shot.shot_made ? 'made' : 'missed'}" x="${h(x - 4)}" y="${h(y - 4)}" width="8" height="8"><title>${h(label)}</title></rect>`;
            })).join('');
            return `<div class="shot-court-card">
                <div class="shot-legend">${names.map((name, index) => `<span class="shot-series-${index + 1}"><i></i>${h(name)}</span>`).join('')}<span><b class="made-key"></b> made</span><span><b class="missed-key"></b> missed</span></div>
                <svg class="shot-court" viewBox="0 0 520 520" role="img" aria-label="Half-court shot chart">
                    ${shotCourtLines()}
                    ${markers}
                </svg>
            </div>`;
        }

        function shotCourtLines() {
            return '<g class="court-lines"><rect x="10" y="10" width="500" height="490"/><line x1="10" y1="500" x2="510" y2="500"/><line x1="230" y1="492" x2="290" y2="492"/><circle cx="260" cy="480" r="8"/><rect x="180" y="310" width="160" height="190"/><circle cx="260" cy="310" r="60"/><path d="M30 500 L30 360 A230 230 0 0 1 490 360 L490 500"/><path d="M200 480 A60 60 0 0 0 320 480"/></g>';
        }

        function shotHeatmap(charts, names) {
            const cells = charts.flatMap((chart, series) => {
                const bins = new Map();
                chart.data.forEach(shot => {
                    const x = Math.max(10, Math.min(510, Number(shot.loc_x) + 260));
                    const y = Math.max(10, Math.min(500, 480 - Number(shot.loc_y)));
                    const key = `${Math.floor(x / 32)}|${Math.floor(y / 32)}`;
                    bins.set(key, (bins.get(key) || 0) + 1);
                });
                const max = Math.max(...bins.values(), 1);
                return [...bins.entries()].map(([key, count]) => {
                    const [column, row] = key.split('|').map(Number);
                    const radius = 7 + 18 * Math.sqrt(count / max);
                    const opacity = 0.18 + 0.55 * (count / max);
                    return `<circle class="shot-heat-cell shot-series-${series + 1}" cx="${h(column * 32 + 16)}" cy="${h(row * 32 + 16)}" r="${h(radius.toFixed(1))}" opacity="${h(opacity.toFixed(2))}"><title>${h(names[series])}: ${h(count)} attempts near this location</title></circle>`;
                });
            }).join('');
            return `<div class="shot-court-card">
                <div class="shot-legend"><strong>Attempt density</strong>${names.map((name, index) => `<span class="shot-series-${index + 1}"><i></i>${h(name)}</span>`).join('')}</div>
                <svg class="shot-court" viewBox="0 0 520 520" role="img" aria-label="Shot density heatmap">
                    ${shotCourtLines()}
                    ${cells}
                </svg>
            </div>`;
        }

        function percentagePoints(value) {
            const number = Number(value);
            if (value === null || value === undefined || !Number.isFinite(number)) return '-';
            return `${number > 0 ? '+' : ''}${(number * 100).toFixed(1)} pp`;
        }

        function shotZoneTable(charts, names) {
            const zoneKeys = [...new Set(charts.flatMap(chart => chart.zones.map(zone => `${zone.zone_basic}|${zone.zone_area}|${zone.zone_range}`)))];
            if (!zoneKeys.length) return '<div class="empty-message">No attempts match these filters.</div>';
            const maps = charts.map(chart => new Map(chart.zones.map(zone => [`${zone.zone_basic}|${zone.zone_area}|${zone.zone_range}`, zone])));
            return `<div class="table-container shot-zones"><div class="table-scroll"><table>
                <thead><tr><th>Zone</th>${names.map(name => `<th>${h(name)}</th>`).join('')}</tr></thead>
                <tbody>${zoneKeys.map(key => {
                    const [basic, area, range] = key.split('|');
                    return `<tr><td><strong>${h(basic)}</strong><br><span class="detail-meta">${h(area)} · ${h(range)}</span></td>${maps.map(map => {
                        const zone = map.get(key);
                        return `<td class="num">${zone ? `
                            <strong>${h(zone.makes)}/${h(zone.attempts)} · ${h(pct(zone.fg_pct))}</strong><br>
                            <span class="detail-meta">${h(pct(zone.frequency))} frequency · ${h(present(zone.points_per_shot))} PPS${zone.fg_pct_vs_league === null ? '' : ` · ${h(percentagePoints(zone.fg_pct_vs_league))} vs league`}</span>
                        ` : '-'}</td>`;
                    }).join('')}</tr>`;
                }).join('')}</tbody>
            </table></div></div>`;
        }

        function navigateComparison(type) {
            const prefix = type === 'players' ? 'compare-player' : 'compare-team';
            const first = document.getElementById(`${prefix}-one`).value;
            const second = document.getElementById(`${prefix}-two`).value;
            const result = document.getElementById(`${type === 'players' ? 'player' : 'team'}-comparison-result`);
            if (!first || !second || first === second) {
                showStatus(result, 'error', `Select two distinct ${type}.`);
                return;
            }
            window.location.hash = `compare/${type}/${encodeURIComponent(first)}/${encodeURIComponent(second)}`;
        }

        function setComparisonSelection(type, first, second) {
            const prefix = type === 'players' ? 'compare-player' : 'compare-team';
            document.getElementById(`${prefix}-one`).value = first;
            document.getElementById(`${prefix}-two`).value = second;
        }

        async function loadComparison(type, first, second) {
            const result = document.getElementById(`${type === 'players' ? 'player' : 'team'}-comparison-result`);
            showLoading(result, `${type} comparison`);
            try {
                if (type === 'players') await renderPlayerComparison(result, first, second);
                else await renderTeamComparison(result, first, second);
            } catch (error) {
                showError(result, `${type} comparison`, error);
            }
        }

        function comparisonMetrics(metrics) {
            return `<div class="comparison-metrics">${metrics.map(([label, value]) => `
                <div class="comparison-metric"><strong>${h(present(value))}</strong><span>${h(label)}</span></div>
            `).join('')}</div>`;
        }

        function trendChart(games, name) {
            const values = [...games].reverse().map(game => Number(game.points));
            if (!values.length) return '<p class="detail-meta">No recent games available.</p>';
            const max = Math.max(...values, 1), width = 300, height = 70, pad = 5;
            const points = values.map((value, index) => {
                const x = values.length === 1 ? width / 2 : pad + index * (width - pad * 2) / (values.length - 1);
                const y = height - pad - value / max * (height - pad * 2);
                return `${x.toFixed(1)},${y.toFixed(1)}`;
            }).join(' ');
            return `<svg class="trend-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${h(name)} points over the last ${values.length} games">
                <line class="trend-axis" x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}"></line>
                <polyline class="trend-line" points="${points}"></polyline>
            </svg>`;
        }

        async function renderPlayerComparison(container, first, second) {
            const params = new URLSearchParams({season});
            params.append('player_ids', first);
            params.append('player_ids', second);
            const [comparison, firstGames, secondGames] = await Promise.all([
                api(`/api/comparisons/players?${params}`),
                api(`/api/players/${encodeURIComponent(first)}/games?${new URLSearchParams({season, limit: 10})}`),
                api(`/api/players/${encodeURIComponent(second)}/games?${new URLSearchParams({season, limit: 10})}`)
            ]);
            const logs = [firstGames.data, secondGames.data];
            container.innerHTML = `<div class="comparison-grid">${comparison.data.map((player, index) => `
                <article class="comparison-card">
                    <h3><a class="clickable" href="#player/${encodeURIComponent(player.player_id)}" data-action="player">${h(player.player_name)}</a></h3>
                    <p class="detail-meta">${h(player.team_abbr)} &middot; ${h(season)} Regular Season</p>
                    ${comparisonMetrics([
                        ['GP', player.games_played], ['MPG', player.mpg], ['PPG', player.ppg],
                        ['RPG', player.rpg], ['APG', player.apg], ['SPG', player.spg],
                        ['BPG', player.bpg], ['FG%', pct(player.fg_pct)], ['3P%', pct(player.fg3_pct)],
                        ['FT%', pct(player.ft_pct)]
                    ])}
                    <h4 class="section-subtitle">Recent scoring trend</h4>
                    ${trendChart(logs[index], player.player_name)}
                </article>
            `).join('')}</div>`;
        }

        async function renderTeamComparison(container, first, second) {
            const params = new URLSearchParams({season});
            params.append('team_ids', first);
            params.append('team_ids', second);
            const comparison = await api(`/api/comparisons/teams?${params}`);
            const cards = comparison.data.map(entry => {
                const team = entry.team, stats = entry.stats;
                return `<article class="comparison-card">
                    <h3><a class="clickable" href="#team/${encodeURIComponent(team.id)}" data-action="team">${h(team.full_name)}</a></h3>
                    <p class="detail-meta">${h(season)} Regular Season</p>
                    ${comparisonMetrics([
                        ['Record', `${stats.wins}-${stats.losses}`], ['Win%', pct(stats.win_pct)], ['PPG', stats.ppg],
                        ['Opp PPG', stats.opponent_ppg], ['Point diff', stats.point_diff], ['RPG', stats.rpg],
                        ['APG', stats.apg], ['eFG%', pct(stats.efg_pct)], ['FG%', pct(stats.fg_pct)],
                        ['3P%', pct(stats.fg3_pct)], ['Last 10', `${stats.last_10_wins}-${stats.last_10_losses}`]
                    ])}
                </article>`;
            }).join('');
            const h2h = comparison.head_to_head;
            const [firstTeam, secondTeam] = comparison.data.map(entry => entry.team);
            container.innerHTML = `<div class="comparison-grid">${cards}</div>
                <div class="head-to-head">
                    <h3>Head-to-head</h3>
                    <p>${h(h2h.games_played)} games &middot; ${h(firstTeam.abbreviation)} ${h(h2h.first_team_wins)}-${h(h2h.second_team_wins)} ${h(secondTeam.abbreviation)}</p>
                    <p class="detail-meta">Average score: ${h(firstTeam.abbreviation)} ${h(h2h.first_team_ppg)} &middot; ${h(secondTeam.abbreviation)} ${h(h2h.second_team_ppg)}</p>
                </div>`;
        }

        async function loadStandings() {
            const c = document.getElementById('standings-table');
            showLoading(c, 'standings');
            try {
                const d = await api(`/api/standings?${new URLSearchParams({season})}`);
                c.innerHTML = `<table>
                    <thead><tr><th class="col-rank">#</th><th>Team</th><th>W</th><th>L</th><th>PCT</th><th class="col-meter"></th></tr></thead>
                    <tbody>${d.map((t, i) => `
                        <tr>
                            <td><span class="standings-rank ${i < 10 ? 'playoff' : ''}">${i + 1}</span></td>
                            <td><a class="clickable" href="#team/${encodeURIComponent(t.team_id)}" data-action="team">${h(t.team_name)}</a></td>
                            <td class="num positive strong">${h(present(t.wins))}</td>
                            <td class="num">${h(present(t.losses))}</td>
                            <td class="num strong">${h(pct(t.win_pct))}</td>
                            <td><progress class="win-pct-progress" max="1" value="${h(Math.min(1, Math.max(0, Number(t.win_pct) || 0)))}" aria-label="${h(t.team_name)} win percentage"></progress></td>
                        </tr>
                    `).join('')}</tbody>
                </table>`;
            } catch(e) { showError(c, 'standings', e); }
        }

        async function loadLeaders() {
            const stat = document.getElementById('leaders-stat').value;
            const statLabels = {points:'PPG', rebounds:'RPG', assists:'APG', steals:'SPG', blocks:'BPG'};
            const c = document.getElementById('leaders-grid');
            showLoading(c, 'leaders');
            try {
                const d = await api(`/api/leaders/${encodeURIComponent(stat)}?${new URLSearchParams({season, limit: 12})}`);
                document.getElementById('leaders-info').textContent = `(minimum ${d.minimum_games} games)`;
                c.innerHTML = d.data.map(p => `
                    <div class="stat-card">
                        <div class="stat-card-header">
                            <div>
                                <a class="stat-card-name clickable" href="#player/${encodeURIComponent(p.player_id)}" data-action="player">${h(p.player_name)}</a>
                                <div class="stat-card-team">${h(p.team_abbr)} &middot; ${h(present(p.games_played))} GP</div>
                            </div>
                            <div class="stat-card-rank ${p.rank <= 3 ? 'top3' : ''}">${h(present(p.rank))}</div>
                        </div>
                        <div class="stat-card-value">${h(present(p.value))}</div>
                        <div class="stat-card-label">${h(statLabels[stat])}</div>
                    </div>
                `).join('');
            } catch(e) { showError(c, 'leaders', e); }
        }

        async function loadGames(reset = true) {
            if (reset) page.games.o = 0;
            const team = document.getElementById('games-team').value;
            const sort = document.getElementById('games-sort').value;
            const c = document.getElementById('games-grid');
            showLoading(c, 'games');
            try {
                const p = new URLSearchParams({season, limit: page.games.l, offset: page.games.o, sort});
                if (team) p.append('team_id', team);
                const d = await api(`/api/games?${p}`);
                page.games.t = d.total;
                document.getElementById('games-info').textContent = `(${d.total} total)`;
                c.innerHTML = d.data.map(g => {
                    const homeWin = g.home_score > g.away_score;
                    return `
                        <a class="game-card" href="#game/${encodeURIComponent(g.id)}" data-action="game">
                            <div class="game-card-date">${h(present(g.game_date, 'TBD'))}</div>
                            <div class="game-card-teams">
                                <div class="game-team-row ${!homeWin ? 'winner' : ''}">
                                    <span class="game-team-name">${h(g.away_team)}</span>
                                    <span class="game-team-score">${h(present(g.away_score))}</span>
                                </div>
                                <div class="game-team-row ${homeWin ? 'winner' : ''}">
                                    <span class="game-team-name">@ ${h(g.home_team)}</span>
                                    <span class="game-team-score">${h(present(g.home_score))}</span>
                                </div>
                            </div>
                        </a>
                    `;
                }).join('');
                renderPagination('games');
            } catch(e) { showError(c, 'games', e); }
        }

        async function loadPlayers(reset = true) {
            if (reset) page.players.o = 0;
            const search = document.getElementById('player-search').value;
            const active = document.getElementById('player-active').value;
            const c = document.getElementById('players-table');
            showLoading(c, 'players');
            try {
                const p = new URLSearchParams({limit: page.players.l, offset: page.players.o});
                if (search) p.append('search', search);
                if (active) p.append('active', active);
                const d = await api(`/api/players?${p}`);
                page.players.t = d.total;
                document.getElementById('players-info').textContent = `(${d.total} total)`;
                c.innerHTML = `<table>
                    <thead><tr><th>Player</th><th>Status</th></tr></thead>
                    <tbody>${d.data.map(p => `
                        <tr>
                            <td><a class="clickable" href="#player/${encodeURIComponent(p.id)}" data-action="player">${h(p.full_name)}</a></td>
                            <td><span class="badge badge-${p.is_active ? 'active' : 'inactive'}">${p.is_active ? 'Active' : 'Inactive'}</span></td>
                        </tr>
                    `).join('')}</tbody>
                </table>`;
                renderPagination('players');
            } catch(e) { showError(c, 'players', e); }
        }

        function renderPagination(key) {
            const s = page[key];
            const pg = Math.floor(s.o / s.l) + 1;
            const tot = Math.ceil(s.t / s.l);
            document.getElementById(`${key}-pagination`).innerHTML = `
                <button ${s.o === 0 ? 'disabled' : ''} data-action="paginate" data-key="${h(key)}" data-direction="-1">Previous</button>
                <span class="pagination-info">Page ${pg} of ${tot}</span>
                <button ${s.o + s.l >= s.t ? 'disabled' : ''} data-action="paginate" data-key="${h(key)}" data-direction="1">Next</button>
            `;
        }

        function paginate(key, dir) {
            page[key].o += dir * page[key].l;
            if (page[key].o < 0) page[key].o = 0;
            ({players: () => loadPlayers(false), games: () => loadGames(false)})[key]();
        }

        function closeModals() {
            document.querySelectorAll('.modal-overlay').forEach(modal => {
                modal.classList.remove('active');
                modal.setAttribute('aria-hidden', 'true');
            });
            document.body.classList.remove('modal-open');
        }

        function trapDialogFocus(event, modal) {
            const focusable = [...modal.querySelectorAll('a[href], button:not([disabled]), input, select, [tabindex]:not([tabindex="-1"])')];
            if (!focusable.length) return;
            const first = focusable[0], last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        }

        function showModal(id) {
            closeModals();
            const modal = document.getElementById(id);
            modal.classList.add('active');
            modal.setAttribute('aria-hidden', 'false');
            document.body.classList.add('modal-open');
            modal.querySelector('.modal-close').focus();
        }

        function closeDetail() {
            window.location.hash = activeSection;
        }

        async function openPlayer(id) {
            const m = document.getElementById('player-modal');
            const b = document.getElementById('player-modal-body');
            showModal(m.id);
            showLoading(b, 'player');
            try {
                const [p, stats, games] = await Promise.all([
                    api(`/api/players/${encodeURIComponent(id)}`),
                    api(`/api/players/${encodeURIComponent(id)}/stats`).catch(() => []),
                    api(`/api/players/${encodeURIComponent(id)}/games?${new URLSearchParams({season, limit: 10})}`)
                ]);
                document.getElementById('player-modal-title').textContent = p.full_name;
                const cur = stats.find(s => s.season === season);
                b.innerHTML = `
                    <p class="detail-meta">
                        ${cur ? `<a class="clickable" href="#team/${encodeURIComponent(cur.team_id)}" data-action="team">${h(cur.team_abbr)}</a> &middot; ` : ''}
                        ${p.is_active ? 'Active' : 'Inactive'} &middot; ${h(season)} Regular Season
                    </p>
                    <div class="detail-actions"><a class="secondary-button" href="${h(shotRoute('player', id))}">View season shot chart</a></div>
                    <div class="stats-grid">
                        <div class="stat-box"><div class="stat-box-value">${h(present(cur?.ppg))}</div><div class="stat-box-label">PPG</div></div>
                        <div class="stat-box"><div class="stat-box-value">${h(present(cur?.rpg))}</div><div class="stat-box-label">RPG</div></div>
                        <div class="stat-box"><div class="stat-box-value">${h(present(cur?.apg))}</div><div class="stat-box-label">APG</div></div>
                        <div class="stat-box"><div class="stat-box-value">${h(present(cur?.spg))}</div><div class="stat-box-label">SPG</div></div>
                        <div class="stat-box"><div class="stat-box-value">${h(present(cur?.bpg))}</div><div class="stat-box-label">BPG</div></div>
                        <div class="stat-box"><div class="stat-box-value">${h(present(cur?.mpg))}</div><div class="stat-box-label">MPG</div></div>
                        <div class="stat-box"><div class="stat-box-value">${h(present(cur?.games_played))}</div><div class="stat-box-label">GP</div></div>
                    </div>
                    ${stats.length ? `
                        <h3 class="section-subtitle">Season Statistics</h3>
                        <div class="table-container"><div class="table-scroll">
                            <table>
                                <thead><tr><th>Season</th><th>GP</th><th>PPG</th><th>RPG</th><th>APG</th><th>FG%</th><th>3P%</th><th>FT%</th></tr></thead>
                                <tbody>${stats.map(s => `
                                    <tr>
                                        <td class="strong">${h(present(s.season))}</td>
                                        <td class="num">${h(present(s.games_played))}</td>
                                        <td class="num highlight-points">${h(present(s.ppg))}</td>
                                        <td class="num">${h(present(s.rpg))}</td>
                                        <td class="num">${h(present(s.apg))}</td>
                                        <td class="num">${h(pct(s.fg_pct))}</td>
                                        <td class="num">${h(pct(s.fg3_pct))}</td>
                                        <td class="num">${h(pct(s.ft_pct))}</td>
                                    </tr>
                                `).join('')}</tbody>
                            </table>
                        </div></div>
                    ` : '<p class="empty-message">No statistics available</p>'}
                    <div class="detail-section">
                        <h3 class="section-subtitle">Recent Games</h3>
                        ${playerGameLogTable(games.data, id)}
                    </div>
                `;
            } catch(e) { showError(b, 'player', e); }
        }

        function playerGameLogTable(games, playerId) {
            if (!games.length) return '<p class="detail-meta">No games available.</p>';
            return `<div class="table-container"><div class="table-scroll"><table>
                <thead><tr><th>Date</th><th>Matchup</th><th>Result</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>FG</th><th>3PT</th><th>+/-</th><th>Shots</th></tr></thead>
                <tbody>${games.map(g => `
                    <tr>
                        <td><a class="clickable" href="#game/${encodeURIComponent(g.game_id)}" data-action="game">${h(present(g.game_date))}</a></td>
                        <td>${g.is_home ? 'vs' : '@'} ${h(g.opponent_abbr)}</td>
                        <td><span class="badge badge-${g.result === 'W' ? 'win' : 'loss'}">${h(g.result)} ${h(g.team_score)}-${h(g.opponent_score)}</span></td>
                        <td class="num">${h(present(g.minutes))}</td>
                        <td class="num strong">${h(present(g.points))}</td>
                        <td class="num">${h(present(g.rebounds))}</td>
                        <td class="num">${h(present(g.assists))}</td>
                        <td class="num">${h(g.fgm)}-${h(g.fga)}</td>
                        <td class="num">${h(g.fg3m)}-${h(g.fg3a)}</td>
                        <td class="num">${g.plus_minus > 0 ? '+' : ''}${h(present(g.plus_minus, 0))}</td>
                        <td><a class="context-link" href="${h(contextualShotRoute('player', playerId, g.game_id))}">Chart</a></td>
                    </tr>
                `).join('')}</tbody>
            </table></div></div>`;
        }

        async function openGame(id) {
            const m = document.getElementById('game-modal');
            const b = document.getElementById('game-modal-body');
            showModal(m.id);
            showLoading(b, 'game');
            try {
                const d = await api(`/api/games/${encodeURIComponent(id)}/boxscore`);
                const g = d.game;
                const homeWin = g.home_score > g.away_score;
                document.getElementById('game-modal-title').textContent = `${g.away_team} @ ${g.home_team}`;
                b.innerHTML = `
                    <div class="game-score-display">
                        <div class="game-score-date">${h(present(g.game_date, ''))}</div>
                        <div class="game-score-teams">
                            <div class="game-score-team">
                                <a class="game-score-team-name clickable" href="#team/${encodeURIComponent(g.away_team_id)}" data-action="team">${h(g.away_team)}</a>
                                <div class="game-score-team-score ${!homeWin ? 'winner' : ''}">${h(present(g.away_score))}</div>
                            </div>
                            <div class="game-score-vs">-</div>
                            <div class="game-score-team">
                                <a class="game-score-team-name clickable" href="#team/${encodeURIComponent(g.home_team_id)}" data-action="team">${h(g.home_team)}</a>
                                <div class="game-score-team-score ${homeWin ? 'winner' : ''}">${h(present(g.home_score))}</div>
                            </div>
                        </div>
                    </div>
                    <div class="detail-actions">
                        <a class="secondary-button" href="${h(contextualShotRoute('team', g.away_team_id, g.id, g.home_team_id))}">Compare game shot charts</a>
                    </div>
                    <h3 class="section-subtitle">${h(g.away_team)}</h3>
                    ${boxscoreTable(d.away_players, g.id)}
                    <h3 class="section-subtitle spaced-title">${h(g.home_team)}</h3>
                    ${boxscoreTable(d.home_players, g.id)}
                `;
            } catch(e) { showError(b, 'game', e); }
        }

        function boxscoreTable(players, gameId) {
            return `<div class="table-container"><div class="table-scroll"><table>
                <thead><tr><th>Player</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>FG</th><th>3PT</th><th>FT</th><th>+/-</th><th>Shots</th></tr></thead>
                <tbody>${players.map(p => `
                    <tr>
                        <td><a class="clickable" href="#player/${encodeURIComponent(p.player_id)}" data-action="player">${h(p.player_name)}</a></td>
                        <td class="num">${h(p.minutes === null || p.minutes === undefined ? '-' : Math.round(Number(p.minutes)))}</td>
                        <td class="num ${p.points >= 20 ? 'highlight-points' : ''}">${h(present(p.points))}</td>
                        <td class="num ${p.rebounds >= 10 ? 'highlight-rebounds' : ''}">${h(present(p.rebounds))}</td>
                        <td class="num ${p.assists >= 10 ? 'highlight-assists' : ''}">${h(present(p.assists))}</td>
                        <td class="num">${h(present(p.steals))}</td>
                        <td class="num">${h(present(p.blocks))}</td>
                        <td class="num">${h(present(p.fgm))}-${h(present(p.fga))}</td>
                        <td class="num">${h(present(p.fg3m))}-${h(present(p.fg3a))}</td>
                        <td class="num">${h(present(p.ftm))}-${h(present(p.fta))}</td>
                        <td class="num ${p.plus_minus > 0 ? 'positive' : p.plus_minus < 0 ? 'negative' : ''}">${p.plus_minus > 0 ? '+' : ''}${h(present(p.plus_minus, 0))}</td>
                        <td>${p.fga ? `<a class="context-link" href="${h(contextualShotRoute('player', p.player_id, gameId))}">Chart</a>` : '-'}</td>
                    </tr>
                `).join('')}</tbody>
            </table></div></div>`;
        }

        async function openTeam(id) {
            const m = document.getElementById('team-modal');
            const b = document.getElementById('team-modal-body');
            showModal(m.id);
            showLoading(b, 'team');
            try {
                const [t, summary, players, games] = await Promise.all([
                    api(`/api/teams/${encodeURIComponent(id)}`),
                    api(`/api/teams/${encodeURIComponent(id)}/stats?${new URLSearchParams({season})}`),
                    api(`/api/teams/${encodeURIComponent(id)}/players?${new URLSearchParams({season, limit: 12})}`),
                    api(`/api/games?${new URLSearchParams({season, team_id: id, limit: 10})}`)
                ]);
                document.getElementById('team-modal-title').textContent = t.full_name;
                b.innerHTML = `
                    <p class="detail-meta">${h(t.city)}, ${h(t.state)} &middot; Founded ${h(present(t.year_founded))} &middot; ${h(season)} Regular Season</p>
                    <div class="detail-actions"><a class="secondary-button" href="${h(shotRoute('team', id))}">View season shot chart</a></div>
                    <div class="stats-grid">
                        <div class="stat-box"><div class="stat-box-value">${h(summary.wins)}-${h(summary.losses)}</div><div class="stat-box-label">Record</div></div>
                        <div class="stat-box"><div class="stat-box-value">${h(pct(summary.win_pct))}</div><div class="stat-box-label">Win%</div></div>
                        <div class="stat-box"><div class="stat-box-value">${h(summary.ppg)}</div><div class="stat-box-label">PPG</div></div>
                        <div class="stat-box"><div class="stat-box-value">${h(summary.opponent_ppg)}</div><div class="stat-box-label">Opp PPG</div></div>
                        <div class="stat-box"><div class="stat-box-value">${summary.point_diff > 0 ? '+' : ''}${h(summary.point_diff)}</div><div class="stat-box-label">Point Diff</div></div>
                        <div class="stat-box"><div class="stat-box-value">${h(summary.rpg)}</div><div class="stat-box-label">RPG</div></div>
                        <div class="stat-box"><div class="stat-box-value">${h(summary.apg)}</div><div class="stat-box-label">APG</div></div>
                    </div>
                    <div class="detail-columns">
                        <section>
                            <h3 class="section-subtitle">Team Profile</h3>
                            <div class="table-container"><div class="table-scroll"><table>
                                <tbody>
                                    <tr><th>Home</th><td class="num">${h(summary.home_wins)}-${h(summary.home_losses)}</td></tr>
                                    <tr><th>Away</th><td class="num">${h(summary.away_wins)}-${h(summary.away_losses)}</td></tr>
                                    <tr><th>Last 10</th><td class="num">${h(summary.last_10_wins)}-${h(summary.last_10_losses)}</td></tr>
                                    <tr><th>eFG%</th><td class="num">${h(pct(summary.efg_pct))}</td></tr>
                                    <tr><th>FG%</th><td class="num">${h(pct(summary.fg_pct))}</td></tr>
                                    <tr><th>3P%</th><td class="num">${h(pct(summary.fg3_pct))}</td></tr>
                                    <tr><th>FT%</th><td class="num">${h(pct(summary.ft_pct))}</td></tr>
                                </tbody>
                            </table></div></div>
                        </section>
                        <section>
                            <h3 class="section-subtitle">Player Leaders</h3>
                            <div class="table-container"><div class="table-scroll"><table>
                                <thead><tr><th>Player</th><th>GP</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th></tr></thead>
                                <tbody>${players.data.map(p => `
                                    <tr>
                                        <td><a class="clickable" href="#player/${encodeURIComponent(p.player_id)}" data-action="player">${h(p.player_name)}</a></td>
                                        <td class="num">${h(p.games_played)}</td>
                                        <td class="num">${h(present(p.mpg))}</td>
                                        <td class="num strong">${h(p.ppg)}</td>
                                        <td class="num">${h(p.rpg)}</td>
                                        <td class="num">${h(p.apg)}</td>
                                    </tr>
                                `).join('')}</tbody>
                            </table></div></div>
                        </section>
                    </div>
                    <div class="detail-section">
                        <h3 class="section-subtitle">Recent Games</h3>
                        ${teamGameTable(games.data, id)}
                    </div>
                `;
            } catch(e) { showError(b, 'team', e); }
        }

        function teamGameTable(games, teamId) {
            return `<div class="table-container"><div class="table-scroll"><table>
                <thead><tr><th>Date</th><th>Opponent</th><th>Result</th><th>Score</th><th>Shots</th></tr></thead>
                <tbody>${games.map(g => {
                    const home = String(g.home_team_id) === String(teamId);
                    const opponent = home ? g.away_team : g.home_team;
                    const teamScore = home ? g.home_score : g.away_score;
                    const opponentScore = home ? g.away_score : g.home_score;
                    const win = teamScore > opponentScore;
                    return `
                        <tr>
                            <td><a class="clickable" href="#game/${encodeURIComponent(g.id)}" data-action="game">${h(present(g.game_date))}</a></td>
                            <td>${home ? 'vs' : '@'} ${h(opponent)}</td>
                            <td><span class="badge badge-${win ? 'win' : 'loss'}">${win ? 'W' : 'L'}</span></td>
                            <td class="num strong">${h(teamScore)}-${h(opponentScore)}</td>
                            <td><a class="context-link" href="${h(contextualShotRoute('team', teamId, g.id))}">Chart</a></td>
                        </tr>`;
                }).join('')}</tbody>
            </table></div></div>`;
        }
