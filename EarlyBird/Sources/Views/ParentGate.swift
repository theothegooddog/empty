import SwiftUI

/// Asks for the parent PIN before running a protected action. With no PIN set, the action runs straight away.
struct ParentGate: ViewModifier {
    @EnvironmentObject private var store: AppStore
    @Binding var pending: (() -> Void)?
    @State private var approved: (() -> Void)?

    func body(content: Content) -> some View {
        content.sheet(
            isPresented: Binding(
                get: { pending != nil },
                set: { if !$0 { pending = nil } }
            ),
            // Run the action only after the PIN sheet is gone, so it can safely present its own sheet.
            onDismiss: {
                approved?()
                approved = nil
            }
        ) {
            PINEntryView(title: "Parent code") { code in
                guard code == store.data.settings.parentPIN else { return false }
                approved = pending
                pending = nil
                return true
            }
        }
    }
}

extension View {
    func parentGate(_ pending: Binding<(() -> Void)?>) -> some View {
        modifier(ParentGate(pending: pending))
    }
}

extension AppStore {
    /// Runs `action` now if there is no PIN, otherwise stores it in `pending` so the gate sheet asks first.
    func protected(_ pending: Binding<(() -> Void)?>, _ action: @escaping () -> Void) {
        if data.settings.parentPIN == nil {
            action()
        } else {
            pending.wrappedValue = action
        }
    }
}

struct PINEntryView: View {
    var title: String
    /// Return true to accept the code and close the sheet.
    var onSubmit: (String) -> Bool

    @Environment(\.dismiss) private var dismiss
    @State private var code = ""
    @State private var wrong = false
    @FocusState private var focused: Bool

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Image(systemName: "lock.fill")
                    .font(.system(size: 44))
                    .foregroundStyle(.orange)
                Text(title).font(.title2.bold())

                HStack(spacing: 16) {
                    ForEach(0..<4, id: \.self) { i in
                        Circle()
                            .fill(i < code.count ? Color.orange : Color.secondary.opacity(0.25))
                            .frame(width: 18, height: 18)
                    }
                }
                .modifier(Shake(trigger: wrong))

                TextField("", text: $code)
                    .keyboardType(.numberPad)
                    .focused($focused)
                    .frame(width: 1, height: 1)
                    .opacity(0.01)
                    .onChange(of: code) { value in
                        let digits = String(value.filter(\.isNumber).prefix(4))
                        if digits != value { code = digits }
                        if digits.count == 4 { submit(digits) }
                    }

                if wrong {
                    Text("That code doesn't match. Try again.")
                        .font(.footnote)
                        .foregroundStyle(.red)
                }
                Spacer()
            }
            .padding(.top, 40)
            .contentShape(Rectangle())
            .onTapGesture { focused = true }
            .onAppear { focused = true }
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium])
    }

    private func submit(_ digits: String) {
        if onSubmit(digits) {
            dismiss()
        } else {
            withAnimation(.default) { wrong.toggle() }
            code = ""
        }
    }
}

private struct Shake: GeometryEffect {
    var trigger: Bool
    var animatableData: CGFloat

    init(trigger: Bool) {
        self.trigger = trigger
        animatableData = trigger ? 1 : 0
    }

    func effectValue(size: CGSize) -> ProjectionTransform {
        ProjectionTransform(CGAffineTransform(translationX: 10 * sin(animatableData * .pi * 4), y: 0))
    }
}
