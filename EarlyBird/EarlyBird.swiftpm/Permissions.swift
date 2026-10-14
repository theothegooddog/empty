import CoreLocation
import UIKit
import UserNotifications

/// Tracks and requests the two permissions Early Bird uses:
/// notifications (morning reminders) and location (checking you're at school).
@MainActor
final class Permissions: NSObject, ObservableObject {
    @Published private(set) var notificationStatus: UNAuthorizationStatus = .notDetermined
    @Published private(set) var locationStatus: CLAuthorizationStatus

    private let locationManager = CLLocationManager()
    private var locationWaiters: [CheckedContinuation<CLLocation?, Never>] = []

    override init() {
        locationStatus = locationManager.authorizationStatus
        super.init()
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyHundredMeters
    }

    var notificationsAllowed: Bool {
        [.authorized, .provisional, .ephemeral].contains(notificationStatus)
    }

    var locationAllowed: Bool {
        locationStatus == .authorizedWhenInUse || locationStatus == .authorizedAlways
    }

    var locationDenied: Bool {
        locationStatus == .denied || locationStatus == .restricted
    }

    /// Re-reads both statuses, e.g. when coming back from the Settings app.
    func refresh() async {
        notificationStatus = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
        locationStatus = locationManager.authorizationStatus
    }

    /// Shows the system notification prompt (only the first time; afterwards iOS answers with the saved choice).
    @discardableResult
    func requestNotifications() async -> Bool {
        let granted = (try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])) ?? false
        await refresh()
        return granted
    }

    /// Shows the system location prompt. The answer arrives through the delegate and updates `locationStatus`.
    func requestLocation() {
        locationManager.requestWhenInUseAuthorization()
    }

    /// One location fix, or nil if location isn't allowed or can't be found.
    func currentLocation() async -> CLLocation? {
        guard locationAllowed else { return nil }
        return await withCheckedContinuation { continuation in
            locationWaiters.append(continuation)
            if locationWaiters.count == 1 {
                locationManager.requestLocation()
            }
        }
    }

    /// Opens Early Bird's page in the Settings app, for turning a permission back on after saying no.
    func openSystemSettings() {
        if let url = URL(string: UIApplication.openSettingsURLString) {
            UIApplication.shared.open(url)
        }
    }

    private func finishLocationRequest(_ location: CLLocation?) {
        let waiters = locationWaiters
        locationWaiters = []
        waiters.forEach { $0.resume(returning: location) }
    }
}

extension Permissions: CLLocationManagerDelegate {
    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let status = manager.authorizationStatus
        Task { @MainActor in self.locationStatus = status }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        let location = locations.last
        Task { @MainActor in self.finishLocationRequest(location) }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in self.finishLocationRequest(nil) }
    }
}
