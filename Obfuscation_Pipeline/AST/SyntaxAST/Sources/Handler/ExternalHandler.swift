//
//  ExternalCode.swift
//  SyntaxAST
//
//  Created by 백승혜 on 8/4/25.
//

import Foundation

internal class ExternalHandler {
    let sourceListPath: String
    let outputDir = "../output/external_to_ast"
    
    init(sourceListPath: String) {
        self.sourceListPath = sourceListPath
    }

    func readAndProcess() throws {
        let fileList = try String(contentsOfFile: sourceListPath)
        let sourcePaths = fileList.split(separator: "\n").map { String($0) }
        
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        
        DispatchQueue.concurrentPerform(iterations: sourcePaths.count) { index in let sourcePath = sourcePaths[index]
            do {
                let extractor = try Extractor(sourcePath: sourcePath)
                extractor.performExtraction()
                
                let (result, _, _) = extractor.store.all()
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
            } catch let posixError as POSIXError {
                print("POSIX Error: code=\(posixError.code.rawValue) desc=\(posixError.localizedDescription)")
            } catch let nsError as NSError {
                print("NSError: domain=\(nsError.domain) code=\(nsError.code) desc=\(nsError.localizedDescription)")
            } catch let e {
                print("Other Error: \(e.localizedDescription)")
            }
        }
    }
}
