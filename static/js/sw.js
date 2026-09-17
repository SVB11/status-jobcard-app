self.addEventListener('push', function(event) {
    let data = { title: 'Status Job Cards', body: 'Job update', url: '/dashboard' };
    try {
        if (event.data) data = Object.assign(data, event.data.json());
    } catch (e) {}
    event.waitUntil(self.registration.showNotification(data.title || 'Status Job Cards', {
        body: data.body || '',
        icon: '/static/images/status_logo_white.png',
        badge: '/static/images/status_logo_white.png',
        data: { url: data.url || '/dashboard' }
    }));
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    const url = (event.notification.data && event.notification.data.url) || '/dashboard';
    event.waitUntil(clients.openWindow(url));
});
