#if canImport(SwiftUI)
import CanonUI
import SwiftUI

/// 작품 목록. 최근에 고친 작품부터 보인다.
public struct ProjectsView: View {
    let model: ProjectsModel
    let open: (ProjectCard) -> Void

    public init(model: ProjectsModel, open: @escaping (ProjectCard) -> Void) {
        self.model = model
        self.open = open
    }

    public var body: some View {
        List {
            if let error = model.error {
                Notice(error, isError: true)
            }
            ForEach(model.groups, id: \.card.name) { group in
                Button { open(group.card) } label: { row(group.card, branches: group.branches.count) }
                    .buttonStyle(.plain)
                if !group.branches.isEmpty {
                    DisclosureGroup("갈래 \(group.branches.count)개 보기") {
                        ForEach(group.branches, id: \.card.name) { b in
                            Button { open(b.card) } label: { branchRow(b) }
                                .buttonStyle(.plain)
                        }
                    }
                    .font(.caption)
                }
            }
        }
        .overlay {
            if model.cards.isEmpty && !model.loading && model.error == nil {
                ContentUnavailableView("작품이 없어요", systemImage: "book.closed", description: Text("웹 화면이나 명령줄에서 새 작품을 만드세요"))
            }
        }
        .navigationTitle("작품")
        .refreshable { await model.load() }
        .task { await model.load() }
    }

    private func row(_ card: ProjectCard, branches: Int) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(ProjectCardText.title(card)).font(.headline)
                Spacer()
                Text(ProjectCardText.progress(card)).font(.caption).foregroundStyle(.secondary)
            }
            Text(ProjectCardText.summary(card, branches: branches)).font(.subheadline)
            Text(ProjectCardText.detail(card)).font(.caption).foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
        .contentShape(Rectangle())
    }

    /// 본편 카드 아래 갈래 한 줄. 갈라진 갈래일수록 들여 쓴다.
    private func branchRow(_ b: ProjectGroup.Branch) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(ProjectCardText.branchTitle(b.card)).font(.subheadline.bold())
            Text(ProjectCardText.branchDetail(b.card)).font(.caption)
            Text(ProjectCardText.folder(b.card)).font(.caption).foregroundStyle(.secondary)
        }
        .padding(.leading, CGFloat(b.depth) * 16)
        .padding(.vertical, 2)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
    }
}
#endif
