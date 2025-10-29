//
//  InternalCode.swift
//  SyntaxAST
//
//  Created by 백승혜 on 8/4/25.
//

import Foundation

internal class InternalHandler {
    let sourceListPath: String
    let outputDir = "../output/source_json"
    let typealias_outputDir = "../output/typealias_json"
    
    init(sourceListPath: String) {
        self.sourceListPath = sourceListPath
    }

    func readAndProcess() throws {
        let fileList = try String(contentsOfFile: sourceListPath)
        let sourcePaths = fileList.split(separator: "\n").map { String($0) }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        // Ensure output directories exist
        do {
            try FileManager.default.createDirectory(at: URL(fileURLWithPath: outputDir), withIntermediateDirectories: true)
        } catch let e as CocoaError {
            fputs("[ERROR] Failed to create outputDir: \(outputDir) (CocoaError: \(e.localizedDescription))\n", stderr)
        } catch let e as POSIXError {
            fputs("[ERROR] Failed to create outputDir: \(outputDir) (POSIXError: \(e.code.rawValue)) - \(e.localizedDescription)\n", stderr)
        } catch let e as NSError {
            fputs("[ERROR] Failed to create outputDir: \(outputDir) (NSError: \(e.domain) / \(e.code)) - \(e.localizedDescription)\n", stderr)
        }
        do {
            try FileManager.default.createDirectory(at: URL(fileURLWithPath: typealias_outputDir), withIntermediateDirectories: true)
        } catch let e as CocoaError {
            fputs("[ERROR] Failed to create typealias_outputDir: \(typealias_outputDir) (CocoaError: \(e.localizedDescription))\n", stderr)
        } catch let e as POSIXError {
            fputs("[ERROR] Failed to create typealias_outputDir: \(typealias_outputDir) (POSIXError: \(e.code.rawValue)) - \(e.localizedDescription)\n", stderr)
        } catch let e as NSError {
            fputs("[ERROR] Failed to create typealias_outputDir: \(typealias_outputDir) (NSError: \(e.domain) / \(e.code)) - \(e.localizedDescription)\n", stderr)
        }
        var allImports = [Set<String>](repeating: [], count: sourcePaths.count)
        var allTypeResults = [[TypealiasInfo]](repeating: [], count: sourcePaths.count)
        
        DispatchQueue.concurrentPerform(iterations: sourcePaths.count) { index in let sourcePath = sourcePaths[index]
            do {
                let extractor = try Extractor(sourcePath: sourcePath)
                extractor.performExtraction()
                let (result, typealiasResult, importResult) = extractor.store.all()
                
                allTypeResults[index] = typealiasResult
                allImports[index] = importResult
                
                let jsonData = try encoder.encode(result)
                
                let sourceURL = URL(fileURLWithPath: sourcePath)
                let fileName = sourceURL.deletingPathExtension().lastPathComponent
                let fileNameWithCount = "\(index)_\(fileName)"
                
                var outputURL = URL(fileURLWithPath: outputDir)
                    .appendingPathComponent(fileNameWithCount)
                    .appendingPathExtension("json")
                
                try jsonData.write(to: outputURL)
            } catch let encodingError as EncodingError {
                print("Encoding Error: \(encodingError)")
            } catch let cocoaError as CocoaError {
                print("Cocoa Error: \(cocoaError.localizedDescription)")
            } catch let posix as POSIXError {
                print("POSIX Error: code=\(posix.code.rawValue) desc=\(posix.localizedDescription)")
            } catch let ns as NSError {
                print("NSError: domain=\(ns.domain) code=\(ns.code) desc=\(ns.localizedDescription)")
            } catch let e {
                print("Other Error: \(e.localizedDescription)")
            }
        }
        
        let importResult = allImports.flatMap { $0 }
        if !allImports.isEmpty {
            let importOutputDir = URL(fileURLWithPath: "../output/")
            do {
                try FileManager.default.createDirectory(at: importOutputDir, withIntermediateDirectories: true)
            } catch let e as CocoaError {
                fputs("[ERROR] Failed to create ../output directory (CocoaError): \(e.localizedDescription)\n", stderr)
            } catch let e as POSIXError {
                fputs("[ERROR] Failed to create ../output directory (POSIX): code=\(e.code.rawValue) desc=\(e.localizedDescription)\n", stderr)
            } catch let e as NSError {
                fputs("[ERROR] Failed to create ../output directory (NSError): \(e.domain)/\(e.code) \(e.localizedDescription)\n", stderr)
            }
            let importOutputFile = importOutputDir.appendingPathComponent("import_list.txt")
            do {
                let jsonData = try encoder.encode(importResult)
                try jsonData.write(to: importOutputFile)
            } catch let e as EncodingError {
                fputs("[ERROR] Failed to encode imports: \(e)\n", stderr)
            } catch let e as CocoaError {
                fputs("[ERROR] Failed to write imports: \(e.localizedDescription)\n", stderr)
            } catch let e as POSIXError {
                fputs("[ERROR] Failed to write imports (POSIX): code=\(e.code.rawValue) desc=\(e.localizedDescription)\n", stderr)
            } catch let e as NSError {
                fputs("[ERROR] Failed to write imports (NSError): \(e.domain)/\(e.code) \(e.localizedDescription)\n", stderr)
            }
        }
        
        let typeResult = allTypeResults.flatMap { $0 }
        if !typeResult.isEmpty {
            let fileName = "typealias"
            let outputURL = URL(fileURLWithPath: typealias_outputDir)
                .appendingPathComponent(fileName)
                .appendingPathExtension("json")
            do {
                let jsonData = try encoder.encode(typeResult)
                try jsonData.write(to: outputURL)
            } catch let e as EncodingError {
                fputs("[ERROR] Failed to encode typealiases: \(e)\n", stderr)
            } catch let e as CocoaError {
                fputs("[ERROR] Failed to write typealiases: \(e.localizedDescription)\n", stderr)
            } catch let e as POSIXError {
                fputs("[ERROR] Failed to write typealiases (POSIX): code=\(e.code.rawValue) desc=\(e.localizedDescription)\n", stderr)
            } catch let e as NSError {
                fputs("[ERROR] Failed to write typealiases (NSError): \(e.domain)/\(e.code) \(e.localizedDescription)\n", stderr)
            }
        }
    }
}
