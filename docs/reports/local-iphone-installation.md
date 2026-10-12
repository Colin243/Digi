# Local iPhone development installation

Distribution decision: personal gift app, installed and updated over a USB cable. No App Store submission or TestFlight flow is planned. VS Code remains the source editor; Xcode is approved for building, signing and testing.

## Requirements

- Full Xcode with an iOS SDK compatible with the recipient iPhone's iOS version.
- An Apple account signed into Xcode and an appropriate signing team.
- Recipient iPhone connected over a data-capable USB cable, unlocked and trusted by the Mac.
- Developer Mode enabled when required by iOS. The device owner completes trust, Developer Mode and account authentication prompts.
- A stable app bundle identifier and matching signing arrangement across updates.

There is currently no native Xcode project in this repository. The following is the installation workflow for the upcoming native target, not a claim that an installable binary exists now.

## Build and install workflow

1. Install Xcode from Apple, complete initial setup, and install the required iOS platform components.
2. Create/open the native DIgit app target and set Signing & Capabilities to the selected team with automatic signing. Validate the camera extension and intent capabilities under that team.
3. Connect and trust the iPhone by cable. Enable Developer Mode following Xcode's device preparation instructions.
4. Select the connected physical iPhone as Xcode's run destination. Build and Run installs and launches the development-signed app.
5. Grant camera and Photos add-only permissions during first use. Take a real shot and confirm the final styled image appears in Apple Photos.
6. Test volume buttons, Action button configuration and Camera Control on equipped hardware. Test permission denial, app termination during a pending save, and Lock Screen handoff separately.
7. For updates, reconnect the phone and build/run using the same bundle identifier. Do not delete the app as a routine update step because app-private pending photos could be lost.

## Signing maintenance

Apple's free Personal Team currently allows up to three apps per device and uses provisioning profiles that expire seven days after issuance. The app must be rebuilt and reinstalled after expiration. This makes a free development build a gift requiring frequent maintenance, not a permanent cable transfer.

For a recipient's device, settle whether they use their own Personal Team for local development or the device is registered with an appropriate paid developer team. Paid development/ad hoc signing can support other private-device workflows but still depends on profile/certificate validity and membership; do not promise indefinite operation. Inspect actual generated profile expiration and record who renews/reinstalls it. No membership purchase or account modification has been performed.

Sources:

- https://developer.apple.com/help/account/basics/about-your-developer-account
- https://help.apple.com/xcode/mac/current/en.lproj/devdc0193470.html
- https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device
- https://developer.apple.com/help/account/provisioning-profiles/create-a-development-provisioning-profile
