import SwiftUI

struct RewardsView: View {
    @EnvironmentObject private var store: AppStore
    @State private var confirming: Reward?
    @State private var showingAdd = false
    @State private var gated: (() -> Void)?

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack {
                        VStack(alignment: .leading) {
                            Text("You have").foregroundStyle(.secondary)
                            Text("\(store.balance) points")
                                .font(.largeTitle.bold().monospacedDigit())
                        }
                        Spacer()
                        Image(systemName: "star.circle.fill")
                            .font(.system(size: 48))
                            .foregroundStyle(.orange)
                    }
                    .padding(.vertical, 6)
                }

                if !store.unusedRedemptions.isEmpty {
                    Section {
                        ForEach(store.unusedRedemptions) { redemption in
                            HStack {
                                Image(systemName: redemption.category.symbol)
                                    .foregroundStyle(.orange)
                                    .frame(width: 28)
                                VStack(alignment: .leading) {
                                    Text(redemption.title)
                                    Text(redemption.date.formatted(date: .abbreviated, time: .omitted))
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                                Spacer()
                                Button("Used") {
                                    store.protected($gated) { store.markUsed(redemption) }
                                }
                                .buttonStyle(.bordered)
                            }
                        }
                    } header: {
                        Text("Ready to cash in")
                    } footer: {
                        Text("Show these to a grown-up. They tap Used when you get your reward.")
                    }
                }

                ForEach(RewardCategory.allCases) { category in
                    let rewards = store.data.rewards.filter { $0.category == category }
                    if !rewards.isEmpty {
                        Section(category.label) {
                            ForEach(rewards) { reward in
                                RewardRow(reward: reward, affordable: store.balance >= reward.cost) {
                                    confirming = reward
                                }
                                .swipeActions {
                                    Button("Delete", role: .destructive) {
                                        store.protected($gated) {
                                            store.data.rewards.removeAll { $0.id == reward.id }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            .navigationTitle("Rewards")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        store.protected($gated) { showingAdd = true }
                    } label: {
                        Label("Add reward", systemImage: "plus")
                    }
                }
            }
            .confirmationDialog(
                confirming.map { "Spend \($0.cost) points on \"\($0.title)\"?" } ?? "",
                isPresented: Binding(get: { confirming != nil }, set: { if !$0 { confirming = nil } }),
                titleVisibility: .visible
            ) {
                Button("Get it!") {
                    if let reward = confirming, store.redeem(reward) {
                        UINotificationFeedbackGenerator().notificationOccurred(.success)
                    }
                    confirming = nil
                }
                Button("Not now", role: .cancel) { confirming = nil }
            }
            .sheet(isPresented: $showingAdd) {
                AddRewardView()
            }
            .parentGate($gated)
        }
    }
}

private struct RewardRow: View {
    var reward: Reward
    var affordable: Bool
    var onRedeem: () -> Void

    var body: some View {
        HStack {
            Image(systemName: reward.category.symbol)
                .foregroundStyle(.orange)
                .frame(width: 28)
            Text(reward.title)
            Spacer()
            Button(action: onRedeem) {
                Text("\(reward.cost)")
                    .font(.subheadline.bold().monospacedDigit())
                    .frame(minWidth: 44)
            }
            .buttonStyle(.borderedProminent)
            .disabled(!affordable)
            .accessibilityLabel("Redeem for \(reward.cost) points")
        }
    }
}

private struct AddRewardView: View {
    @EnvironmentObject private var store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var cost = 50
    @State private var category: RewardCategory = .screenTime

    var body: some View {
        NavigationStack {
            Form {
                TextField("Reward, e.g. 20 min of Minecraft", text: $title)
                Picker("Type", selection: $category) {
                    ForEach(RewardCategory.allCases) { c in
                        Label(c.label, systemImage: c.symbol).tag(c)
                    }
                }
                Stepper("Costs \(cost) points", value: $cost, in: 5...2000, step: 5)
            }
            .navigationTitle("New reward")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Add") {
                        store.addReward(Reward(title: title.trimmingCharacters(in: .whitespaces), cost: cost, category: category))
                        dismiss()
                    }
                    .disabled(title.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
    }
}
