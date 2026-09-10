import SwiftUI

/// `ob2` from the prototype — discipline grid, copy/layout unchanged.
struct OnboardingDisciplineView: View {
    var viewModel: OnboardingViewModel

    private let columns = [GridItem(.flexible(), spacing: FWSpacing.sm), GridItem(.flexible(), spacing: FWSpacing.sm)]

    var body: some View {
        VStack(alignment: .leading, spacing: FWSpacing.xxl) {
            SectionHeader(eyebrow: "STEP 1/3", title: "What do you want to compete in?")

            LazyVGrid(columns: columns, spacing: FWSpacing.sm) {
                ForEach(viewModel.disciplines, id: \.self) { discipline in
                    Button {
                        Task { await viewModel.pickDiscipline(discipline) }
                    } label: {
                        VStack(alignment: .leading, spacing: FWSpacing.xxl) {
                            RoundedRectangle(cornerRadius: FWRadius.small, style: .continuous)
                                .fill(FWColor.surface2)
                                .frame(width: 26, height: 26)
                            Text(discipline)
                                .font(FWTypography.titleSmall)
                                .foregroundStyle(FWColor.textPrimary)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(FWSpacing.lg)
                        .background(FWColor.surface)
                        .overlay(RoundedRectangle(cornerRadius: FWRadius.large, style: .continuous).strokeBorder(FWColor.line))
                        .clipShape(RoundedRectangle(cornerRadius: FWRadius.large, style: .continuous))
                    }
                    .buttonStyle(FWPressableStyle())
                    .accessibilityAddTraits(viewModel.selectedDiscipline == discipline ? .isSelected : [])
                }
            }

            Spacer()
        }
        .padding(.horizontal, FWSpacing.screenHorizontal)
        .padding(.top, 80)
        .padding(.bottom, FWSpacing.xxl)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(FWColor.background)
    }
}
