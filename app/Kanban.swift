import AppKit
import WebKit

// Kanban als Mac-Programm: startet server.py im Hintergrund und zeigt das Board
// in einem eigenen Fenster. Beim Beenden wird der Server wieder gestoppt.
// Läuft der Server schon (z. B. über start.command), wird er nur mitbenutzt.

let adresse = URL(string: "http://localhost:8814")!

final class Programmleitung: NSObject, NSApplicationDelegate, WKUIDelegate {
    private var fenster: NSWindow?
    private var ansicht: WKWebView?
    private var server: Process?
    private var protokoll = ""  // server.log: Fehlertext von Python, falls der Server gleich wieder endet

    func applicationDidFinishLaunching(_ mitteilung: Notification) {
        menueBauen()
        fensterOeffnen()
        switch serverPruefen() {
        case .aktuell:
            ansicht?.load(URLRequest(url: adresse))
        case .alt:
            fehlerZeigen("Ein alter Kanban-Server läuft noch und speichert nicht in die Datenbank. "
                + "Bitte das Terminal-Fenster von start.command schliessen und Kanban neu öffnen.")
        case .keiner where serverStarten():
            warteteAufServer(versuche: 50)
        case .keiner:
            break
        }
    }

    /// Vor dem Beenden warten, bis die Seite ihre letzte Änderung gespeichert hat (höchstens 2 Sekunden).
    func applicationShouldTerminate(_ programm: NSApplication) -> NSApplication.TerminateReply {
        guard let ansicht else { return .terminateNow }
        func pruefen(_ rest: Int) {
            ansicht.evaluateJavaScript("speichertGerade || nochmal") { ergebnis, _ in
                if (ergebnis as? Bool) == true, rest > 0 {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { pruefen(rest - 1) }
                } else {
                    programm.reply(toApplicationShouldTerminate: true)
                }
            }
        }
        pruefen(20)
        return .terminateLater
    }

    func applicationWillTerminate(_ mitteilung: Notification) {
        server?.terminate()
        server?.waitUntilExit()
    }

    /// Fenster zu = Programm beenden.
    func applicationShouldTerminateAfterLastWindowClosed(_ programm: NSApplication) -> Bool { true }

    // MARK: Server

    private func serverStarten() -> Bool {
        guard let ordner = Bundle.main.object(forInfoDictionaryKey: "KanbanOrdner") as? String else {
            fehlerZeigen("Projektordner unbekannt – App bitte mit bauen.sh neu bauen.")
            return false
        }
        let python = ["/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]
            .first { FileManager.default.isExecutableFile(atPath: $0) } ?? "/usr/bin/python3"
        let p = Process()
        p.executableURL = URL(fileURLWithPath: python)
        p.arguments = [ordner + "/server.py"]
        p.currentDirectoryURL = URL(fileURLWithPath: ordner)
        var umgebung = ProcessInfo.processInfo.environment
        umgebung["KEIN_BROWSER"] = "1"
        umgebung.removeValue(forKey: "ANTHROPIC_API_KEY")
        p.environment = umgebung
        protokoll = ordner + "/server.log"
        FileManager.default.createFile(atPath: protokoll, contents: nil)
        if let datei = FileHandle(forWritingAtPath: protokoll) {
            p.standardOutput = datei
            p.standardError = datei
        }
        do {
            try p.run()
            server = p
            return true
        } catch {
            fehlerZeigen("Server konnte nicht starten: \(error.localizedDescription)")
            return false
        }
    }

    enum Serverlage { case keiner, aktuell, alt }

    /// Läuft schon ein Server – und ist es einer, der in kanban.db speichert?
    private func serverPruefen() -> Serverlage {
        var anfrage = URLRequest(url: adresse.appendingPathComponent("api/board"))
        anfrage.timeoutInterval = 0.5
        let fertig = DispatchSemaphore(value: 0)
        var lage = Serverlage.keiner
        URLSession.shared.dataTask(with: anfrage) { _, antwort, _ in
            if let a = antwort as? HTTPURLResponse, a.statusCode == 200 {
                lage = a.value(forHTTPHeaderField: "X-Kanban-Speicher") == "sqlite" ? .aktuell : .alt
            }
            fertig.signal()
        }.resume()
        fertig.wait()
        return lage
    }

    /// Wartet bis zu 10 Sekunden, bis der frisch gestartete Server antwortet.
    private func warteteAufServer(versuche: Int) {
        if serverPruefen() == .aktuell {
            ansicht?.load(URLRequest(url: adresse))
        } else if versuche > 0, server?.isRunning == true {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { self.warteteAufServer(versuche: versuche - 1) }
        } else if let server, !server.isRunning {
            let text = ((try? String(contentsOfFile: protokoll, encoding: .utf8)) ?? "")
                .replacingOccurrences(of: "&", with: "&amp;").replacingOccurrences(of: "<", with: "&lt;")
            fehlerZeigen("Der Kanban-Server ist beim Start abgebrochen. Steht unten „Operation not permitted“: "
                + "Systemeinstellungen › Datenschutz & Sicherheit › Dateien und Ordner › Kanban › Dokumente erlauben."
                + "<pre>\(text)</pre>")
        } else {
            fehlerZeigen("Der Kanban-Server antwortet nicht. Ist Port 8814 von einem anderen Programm belegt?")
        }
    }

    // MARK: Fenster

    private func fensterOeffnen() {
        let w = WKWebView(frame: .zero, configuration: WKWebViewConfiguration())
        w.uiDelegate = self
        let f = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1100, height: 720),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered, defer: false)
        f.title = "Kanban"
        f.contentView = w
        f.contentMinSize = NSSize(width: 600, height: 400)
        f.setFrameAutosaveName("KanbanFenster")  // Größe und Ort merken
        f.center()
        f.isReleasedWhenClosed = false
        f.makeKeyAndOrderFront(nil)
        fenster = f
        ansicht = w
        NSApp.activate(ignoringOtherApps: true)
    }

    private func fehlerZeigen(_ text: String) {
        ansicht?.loadHTMLString(
            "<body style='font:16px -apple-system;padding:40px;color:#222;background:#fff'>\(text)</body>", baseURL: nil)
    }

    // Damit Hinweise und Rückfragen der Seite im Fenster nicht stumm verschluckt werden.
    func webView(_ w: WKWebView, runJavaScriptAlertPanelWithMessage text: String,
                 initiatedByFrame _: WKFrameInfo, completionHandler fertig: @escaping () -> Void) {
        let a = NSAlert(); a.messageText = text; a.runModal(); fertig()
    }

    func webView(_ w: WKWebView, runJavaScriptConfirmPanelWithMessage text: String,
                 initiatedByFrame _: WKFrameInfo, completionHandler fertig: @escaping (Bool) -> Void) {
        let a = NSAlert(); a.messageText = text
        a.addButton(withTitle: "OK"); a.addButton(withTitle: "Abbrechen")
        fertig(a.runModal() == .alertFirstButtonReturn)
    }

    // MARK: Menü (ohne Menü gehen Cmd+Q, Kopieren und Einfügen nicht)

    private func menueBauen() {
        let leiste = NSMenu()
        let app = NSMenu()
        app.addItem(withTitle: "Kanban beenden", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let bearbeiten = NSMenu(title: "Bearbeiten")
        bearbeiten.addItem(withTitle: "Widerrufen", action: Selector(("undo:")), keyEquivalent: "z")
        bearbeiten.addItem(withTitle: "Wiederholen", action: Selector(("redo:")), keyEquivalent: "Z")
        bearbeiten.addItem(.separator())
        bearbeiten.addItem(withTitle: "Ausschneiden", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        bearbeiten.addItem(withTitle: "Kopieren", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        bearbeiten.addItem(withTitle: "Einfügen", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        bearbeiten.addItem(withTitle: "Alles auswählen", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        for menue in [app, bearbeiten] {
            let eintrag = NSMenuItem()
            eintrag.submenu = menue
            leiste.addItem(eintrag)
        }
        NSApp.mainMenu = leiste
    }
}

@main
enum Start {
    /// Muss am Leben bleiben: NSApplication hält den Delegaten nur schwach.
    nonisolated(unsafe) static var leitung: Programmleitung?

    static func main() {
        let programm = NSApplication.shared
        programm.setActivationPolicy(.regular)
        leitung = Programmleitung()
        programm.delegate = leitung
        programm.run()
    }
}
