// swift-tools-version: 5.9

// Swift Playgrounds app package. Open this folder in Swift Playgrounds (iPad or Mac) or in Xcode 15+.

import PackageDescription
import AppleProductTypes

let package = Package(
    name: "Early Bird",
    platforms: [
        .iOS("17.0")
    ],
    products: [
        .iOSApplication(
            name: "Early Bird",
            targets: ["AppModule"],
            bundleIdentifier: "com.example.EarlyBird",
            displayVersion: "1.0",
            bundleVersion: "1",
            appIcon: .placeholder(icon: .clock),
            accentColor: .presetColor(.orange),
            supportedDeviceFamilies: [
                .pad,
                .phone
            ],
            supportedInterfaceOrientations: [
                .portrait,
                .landscapeRight,
                .landscapeLeft,
                .portraitUpsideDown(.when(deviceFamilies: [.pad]))
            ],
            capabilities: [
                .locationWhenInUse(purposeString: "Early Bird checks that you're at school when you tap \"I'm at school!\", so your streak is the real deal.")
            ]
        )
    ],
    targets: [
        .executableTarget(
            name: "AppModule",
            path: "."
        )
    ]
)
