#if canImport(SwiftUI)
import SwiftUI

/// 화면 위쪽 알림 한 줄. 오류는 닫을 때까지 남긴다 (웹 화면의 toast 와 같다).
public struct Notice: View {
    let text: String
    let isError: Bool
    let close: (() -> Void)?

    public init(_ text: String, isError: Bool = false, close: (() -> Void)? = nil) {
        self.text = text
        self.isError = isError
        self.close = close
    }

    public var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: isError ? "exclamationmark.triangle" : "checkmark.circle")
                .foregroundStyle(isError ? Color.red : Color.green)
            Text(text).frame(maxWidth: .infinity, alignment: .leading)
            if let close {
                Button(action: close) { Image(systemName: "xmark") }
                    .buttonStyle(.borderless)
                    .accessibilityLabel("닫기")
            }
        }
        .padding(10)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 8))
    }
}

/// 아직 앱으로 옮기지 않은 화면.
public struct NotPortedYet: View {
    let title: String

    public init(_ title: String) {
        self.title = title
    }

    public var body: some View {
        ContentUnavailableView(title, systemImage: "hammer", description: Text("이 화면은 아직 앱으로 옮기는 중이에요. 웹 화면에서 쓰세요"))
    }
}
#endif
