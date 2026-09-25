self.addEventListener('push', function(event) {
    let data = { title: 'Status Job Cards', body: 'Job update', url: '/dashboard' };
    try {
        if (event.data) data = Object.assign(data, event.data.json());
    } catch (e) {}
    const unread = data.unread || 1;
    event.waitUntil(Promise.all([
        self.registration.showNotification(data.title || 'Status Job Cards', {
            body: data.body || '',
            icon: '/static/images/app_icon_192.png',
            badge: '/static/images/app_icon_192.png',
            data: { url: data.url || '/dashboard' }
        }),
        self.navigator.setAppBadge ? self.navigator.setAppBadge(unread) : Promise.resolve()
    ]));
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    const url = (event.notification.data && event.notification.data.url) || '/dashboard';
    event.waitUntil(clients.openWindow(url));
});
