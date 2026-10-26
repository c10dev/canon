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
            ForEach(model.cards, id: \.name) { card in
                Button { open(card) } label: { row(card) }
                    .buttonStyle(.plain)
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

    private func row(_ card: ProjectCard) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(ProjectCardText.title(card)).font(.headline)
                Spacer()
                Text(ProjectCardText.progress(card)).font(.caption).foregroundStyle(.secondary)
            }
            Text(ProjectCardText.summary(card)).font(.subheadline)
            Text(ProjectCardText.detail(card)).font(.caption).foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
        .contentShape(Rectangle())
    }
}
#endif
