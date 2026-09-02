import PhotosUI
import SwiftUI

/// Wraps `PHPickerViewController` for picking one video.
///
/// Uses the Photos *picker* rather than the photo library API on purpose: the picker
/// runs out of process and returns only the chosen item, so FITWAR needs no library
/// permission at all and can never see anything the user didn't pick. That is the whole
/// permission story for proof selection — there is nothing to deny.
struct ProofVideoPicker: UIViewControllerRepresentable {
    var onPicked: (Data, String) -> Void
    var onProblem: (ProofSelectionProblem) -> Void

    func makeUIViewController(context: Context) -> PHPickerViewController {
        var config = PHPickerConfiguration()
        config.filter = .videos
        config.selectionLimit = 1
        let controller = PHPickerViewController(configuration: config)
        controller.delegate = context.coordinator
        return controller
    }

    func updateUIViewController(_ controller: PHPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(onPicked: onPicked, onProblem: onProblem)
    }

    final class Coordinator: NSObject, PHPickerViewControllerDelegate {
        private let onPicked: (Data, String) -> Void
        private let onProblem: (ProofSelectionProblem) -> Void

        init(
            onPicked: @escaping (Data, String) -> Void,
            onProblem: @escaping (ProofSelectionProblem) -> Void
        ) {
            self.onPicked = onPicked
            self.onProblem = onProblem
        }

        func picker(
            _ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]
        ) {
            picker.dismiss(animated: true)
            guard let provider = results.first?.itemProvider else {
                onProblem(.cancelled)
                return
            }
            // Ask for the two types the server accepts. Anything else is refused here
            // rather than wasting an upload that storage would reject.
            let type = provider.hasItemConformingToTypeIdentifier(UTType.quickTimeMovie.identifier)
                ? UTType.quickTimeMovie
                : UTType.mpeg4Movie
            guard provider.hasItemConformingToTypeIdentifier(type.identifier) else {
                onProblem(.unsupportedType)
                return
            }

            provider.loadFileRepresentation(forTypeIdentifier: type.identifier) { url, _ in
                guard let url, let data = try? Data(contentsOf: url) else {
                    DispatchQueue.main.async { self.onProblem(.unreadable) }
                    return
                }
                let contentType = type == .quickTimeMovie ? "video/quicktime" : "video/mp4"
                DispatchQueue.main.async { self.onPicked(data, contentType) }
            }
        }
    }
}
