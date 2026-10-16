let activeLogMode = 'system';
        let cachedData = null;

        function toggleFeedCard(btn) {
            const container = btn.closest('.feed-container');
            const feedTabs = document.getElementById('feedTabs');
            if (!container || !feedTabs) return;

            if (!container.classList.contains('collapsed')) {
                // Keep a placeholder so the feed returns to its exact position.
                const placeholder = document.createComment('feed-placeholder');
                container.parentNode.insertBefore(placeholder, container);
                container._feedPlaceholder = placeholder;

                container.classList.add('collapsed');
                btn.innerText = '+';
                btn.title = 'Expand Feed';
                feedTabs.appendChild(container);
            } else {
                const placeholder = container._feedPlaceholder;
                container.classList.remove('collapsed');
                btn.innerText = '−';
                btn.title = 'Minimize/Expand';

                if (placeholder && placeholder.parentNode) {
                    placeholder.parentNode.insertBefore(container, placeholder);
                    placeholder.remove();
                } else {
                    document.querySelector('.top-section')?.appendChild(container);
                }
                delete container._feedPlaceholder;
            }
        }

        function toggleTerminal(btn) {
            let container = btn.closest('.terminal-container');
            container.classList.toggle('collapsed');
            btn.innerText = container.classList.contains('collapsed') ? '+' : '−';
        }

        function toggleMetrics(btn) {
            let col = btn.closest('.metrics-col');
            col.classList.toggle('collapsed');
            btn.innerText = col.classList.contains('collapsed') ? '+' : '−';
        }

        function toggleChatPopup() {
            let popup = document.getElementById('chatPopup');
            popup.classList.toggle('active');
            if (popup.classList.contains('active')) document.getElementById('chatInput').focus();
        }

        function switchLogTab(mode) {
            activeLogMode = mode;
            document.getElementById('sysTabBtn').classList.toggle('active', mode === 'system');
            document.getElementById('trkTabBtn').classList.toggle('active', mode === 'tracker');
            renderLogs();
        }

        async function promptAddWatchlistWithPrice() {
            let url = prompt("Enter Product URL to add to Live Watchlist:");
            if (!url) return;
            let targetPriceStr = prompt("Enter Target Price (e.g. 999):", "0");
            if (targetPriceStr === null) return;
            let targetPrice = parseFloat(targetPriceStr) || 0;

            try {
                let res = await fetch('/add_watchlist', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: url, target_price: targetPrice })
                });
                let data = await res.json();
                alert(data.message || "Added successfully!");
                fetchStats();
            } catch (err) {
                alert("Failed to add watchlist item.");
            }
        }

        async function promptAddKeywordFeed() {
            let kw = prompt("Enter product keyword to track in custom feed (e.g. 'fan', 'shoe', 'iphone'):");
            if (!kw) return;
            try {
                let res = await fetch('/add_keyword_feed', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ keyword: kw.trim() })
                });
                let data = await res.json();
                alert(data.message || "Product feed added!");
                fetchStats();
            } catch (err) {
                alert("Failed to add product feed.");
            }
        }

        async function promptUpdateWatchlistSettings(index) {
            if (!cachedData || !cachedData.watched_items || !cachedData.watched_items[index]) return;
            let item = cachedData.watched_items[index];
            
            let newTargetStr = prompt("Enter new Target Price (e.g. 999):", item.target_price > 0 ? item.target_price : "");
            if (newTargetStr === null) return;
            let newTarget = parseFloat(newTargetStr) || 0;

            try {
                let res = await fetch('/update_watchlist_item', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: item.url, target_price: newTarget })
                });
                let data = await res.json();
                alert(data.message || "Updated successfully!");
                fetchStats();
            } catch (err) {
                alert("Failed to update item settings.");
            }
        }

        async function deleteWatchlistItem(index) {
            if (!cachedData || !cachedData.watched_items || !cachedData.watched_items[index]) return;
            let item = cachedData.watched_items[index];

            if (!confirm("Are you sure you want to delete this watchlist item?")) return;
            try {
                let res = await fetch('/delete_watchlist', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: item.url })
                });
                let data = await res.json();
                alert(data.message || "Deleted successfully!");
                fetchStats();
            } catch (err) {
                alert("Failed to delete item.");
            }
        }

        async function toggleTracking() {
            try {
                let res = await fetch('/toggle_tracking', { method: 'POST' });
                let data = await res.json();
                updateTrackingUI(data.tracking_active);
            } catch (err) {
                console.error("Failed to toggle tracking:", err);
            }
        }

        function updateTrackingUI(isActive) {
            let btn = document.getElementById('toggleTrackBtn');
            let dot = document.getElementById('pulseDot');
            if (isActive) {
                btn.innerHTML = "⏸️ Pause Tracking";
                dot.style.backgroundColor = "var(--accent-green)";
            } else {
                btn.innerHTML = "▶️ Resume Tracking";
                dot.style.backgroundColor = "var(--accent-red)";
            }
        }

        async function fetchStats() {
            try {
                let response = await fetch('/stats');
                cachedData = await response.json();
                
                document.getElementById('scannedCount').innerText = cachedData.deals_scanned;
                document.getElementById('postedCount').innerText = cachedData.posted_deals ? cachedData.posted_deals.length : 0;
                document.getElementById('channelsVal').innerText = cachedData.channels_count || 0;
                document.getElementById('uptimeVal').innerText = cachedData.uptime || '0s';
                document.getElementById('dedupVal').innerText = cachedData.dedup_size || 0;

                if (cachedData.recent_deals) {
                    document.getElementById('scanCountBadge').innerText = `${cachedData.recent_deals.length} items`;
                    let container = document.getElementById('scannedList');
                    if (cachedData.recent_deals.length > 0) {
                        let html = '';
                        cachedData.recent_deals.forEach(deal => {
                            html += `
                                <div class="deal-card scanned">
                                    <div class="deal-title"><a href="${deal.url}" target="_blank">${deal.title}</a></div>
                                    <div class="deal-details">
                                        <span>Min: <b>${deal.min_price}</b></span>
                                        <span>Avg: <b>${deal.avg_price}</b></span>
                                    </div>
                                    <div class="deal-footer">
                                        <span class="deal-price">Price: ${deal.price}</span>
                                        <span>${deal.source} • ${deal.time}</span>
                                    </div>
                                </div>
                            `;
                        });
                        container.innerHTML = html;
                    }
                }

                if (cachedData.posted_deals) {
                    document.getElementById('postCountBadge').innerText = `${cachedData.posted_deals.length} items`;
                    let container = document.getElementById('postedList');
                    if (cachedData.posted_deals.length > 0) {
                        let html = '';
                        cachedData.posted_deals.forEach(deal => {
                            html += `
                                <div class="deal-card posted">
                                    <div class="deal-title"><a href="${deal.url}" target="_blank">${deal.title}</a></div>
                                    <div class="deal-details">
                                        <span>Min: <b>${deal.min_price}</b></span>
                                        <span>Avg: <b>${deal.avg_price}</b></span>
                                    </div>
                                    <div class="deal-footer">
                                        <span class="deal-price">Price: ${deal.price}</span>
                                        <span>${deal.source} • ${deal.time}</span>
                                    </div>
                                </div>
                            `;
                        });
                        container.innerHTML = html;
                    }
                }

                if (cachedData.watched_items) {
                    document.getElementById('trackerCountBadge').innerText = `${cachedData.watched_items.length} items`;
                    let container = document.getElementById('trackerList');
                    if (cachedData.watched_items.length > 0) {
                        let html = '';
                        cachedData.watched_items.forEach((item, index) => {
                            let targetPriceText = item.target_price > 0 ? `₹${item.target_price.toLocaleString()}` : 'None';
                            html += `
                                <div class="deal-card tracker" style="display: flex; justify-content: space-between; align-items: center;">
                                    <div style="flex-grow: 1; overflow: hidden; margin-right: 8px;">
                                        <div class="deal-title"><a href="${item.url}" target="_blank">${item.title}</a></div>
                                        <div class="deal-footer">
                                            <span class="deal-price">Live: ${item.price}</span>
                                            <span style="color: var(--accent-yellow);">Target: ${targetPriceText}</span>
                                        </div>
                                    </div>
                                    <div style="display: flex; gap: 4px; flex-shrink: 0;">
                                        <button onclick="promptUpdateWatchlistSettings(${index})" title="Edit Settings" style="background: rgba(56,189,248,0.1); border: 1px solid rgba(56,189,248,0.3); color: var(--accent-blue); padding: 5px 8px; border-radius: 6px; cursor: pointer;">✏️</button>
                                        <button onclick="deleteWatchlistItem(${index})" title="Delete Item" style="background: rgba(248,113,113,0.1); border: 1px solid rgba(248,113,113,0.3); color: var(--accent-red); padding: 5px 8px; border-radius: 6px; cursor: pointer;">🗑️</button>
                                    </div>
                                </div>
                            `;
                        });
                        container.innerHTML = html;
                    } else {
                        container.innerHTML = `<div class="deal-card tracker"><div class="deal-title">Tracking watchlist items...</div></div>`;
                    }
                }

                if (cachedData.keyword_deals) {
                    let kTitle = cachedData.active_keyword ? `📦 Feed: ${cachedData.active_keyword}` : `📦 Product Custom Feed`;
                    document.getElementById('keywordFeedTitle').innerText = kTitle;
                    document.getElementById('keywordCountBadge').innerText = `${cachedData.keyword_deals.length} items`;
                    let container = document.getElementById('keywordList');
                    if (cachedData.keyword_deals.length > 0) {
                        let html = '';
                        cachedData.keyword_deals.forEach(deal => {
                            html += `
                                <div class="deal-card scanned">
                                    <div class="deal-title"><a href="${deal.url}" target="_blank">${deal.title}</a></div>
                                    <div class="deal-footer">
                                        <span class="deal-price">Price: ${deal.price}</span>
                                        <span>${deal.source} • ${deal.time}</span>
                                    </div>
                                </div>
                            `;
                        });
                        container.innerHTML = html;
                    } else {
                        container.innerHTML = `<div class="deal-card scanned"><div class="deal-title">No matching deals for keyword yet...</div></div>`;
                    }
                }

                if (cachedData.cart_items) {
                    document.getElementById('cartCountBadge').innerText = `${cachedData.cart_items.length} items`;
                    let container = document.getElementById('cartList');
                    if (cachedData.cart_items.length > 0) {
                        let html = '';
                        cachedData.cart_items.forEach(item => {
                            html += `
                                <div class="deal-card posted">
                                    <div class="deal-title"><a href="${item.url}" target="_blank">${item.title}</a></div>
                                    <div class="deal-footer">
                                        <span class="deal-price">Price: ${item.price}</span>
                                        <span>Added: ${item.time}</span>
                                    </div>
                                </div>
                            `;
                        });
                        container.innerHTML = html;
                    } else {
                        container.innerHTML = `<div class="deal-card posted"><div class="deal-title">No items added to cart yet...</div></div>`;
                    }
                }

                renderLogs();
            } catch (err) {
                console.error("Dashboard sync error:", err);
            }
        }

        function renderLogs() {
            if (!cachedData) return;
            let logs = activeLogMode === 'system' ? cachedData.recent_logs : cachedData.tracker_logs;
            if (!logs) return;

            document.getElementById('logCountBadge').innerText = `${logs.length} logs`;
            let terminal = document.getElementById('terminalLogs');
            if (logs.length > 0) {
                let html = '';
                logs.forEach(log => {
                    let logClass = log.is_error ? 'log-error' : 'log-info';
                    html += `
                        <div class="log-line">
                            <span class="log-time">[${log.time}]</span>
                            <span class="${logClass}">${log.prefix} ${log.msg}</span>
                        </div>
                    `;
                });
                terminal.innerHTML = html;
            }
        }

        async function sendChatMessage() {
            let inputField = document.getElementById('chatInput');
            let query = inputField.value.trim();
            if (!query) return;

            let chatBox = document.getElementById('chatBox');
            chatBox.innerHTML += `<div class="chat-msg user-msg">${escapeHtml(query)}</div>`;
            inputField.value = '';
            chatBox.scrollTop = chatBox.scrollHeight;

            let loadId = 'loading-' + Date.now();
            chatBox.innerHTML += `<div id="${loadId}" class="chat-msg bot-msg">Thinking & analyzing deals...</div>`;
            chatBox.scrollTop = chatBox.scrollHeight;

            try {
                let res = await fetch(`/search?q=${encodeURIComponent(query)}`);
                let data = await res.json();
                document.getElementById(loadId).remove();

                let botAnswer = data.answer || "No response found.";
                let dealsHtml = "";
                if (data.deals && data.deals.length > 0) {
                    dealsHtml += "<br><br><b>Relevant Deals:</b>";
                    data.deals.forEach(deal => {
                        dealsHtml += `
                            <div style="background: var(--bg-color); border: 1px solid var(--border-color); padding: 6px; border-radius: 6px; margin-top: 5px; font-size: 0.75rem;">
                                <b>${escapeHtml(deal.title)}</b><br>
                                Price: <span style="color: var(--accent-green); font-weight: bold;">${deal.price}</span> | Source: ${deal.source}<br>
                                <a href="${deal.url}" target="_blank" style="color: var(--accent-blue);">View Deal 🔗</a>
                            </div>
                        `;
                    });
                }
                chatBox.innerHTML += `<div class="chat-msg bot-msg">${botAnswer}${dealsHtml}</div>`;
            } catch (err) {
                document.getElementById(loadId).remove();
                chatBox.innerHTML += `<div class="chat-msg bot-msg">Sorry, an error occurred while connecting to AI.</div>`;
            }
            chatBox.scrollTop = chatBox.scrollHeight;
        }

        function handleChatKey(e) {
            if (e.key === 'Enter') sendChatMessage();
        }

        function escapeHtml(text) {
            return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        }

        setInterval(fetchStats, 3000);
        fetchStats();
