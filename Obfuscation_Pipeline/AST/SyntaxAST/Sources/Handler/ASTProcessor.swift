//
//  Extractor.swift
//  SyntaxAST
//
//  Created by 백승혜 on 7/15/25.
//

//  SwiftSyntax 소스코드 파싱 및 추출

import Foundation
import SwiftSyntax
import SwiftParser
import Darwin

internal class Extractor {
    private let sourcePath: String
    private let sourceText: String
    private let syntaxTree: SourceFileSyntax
    var store: ResultStore
    let location: LocationHandler
    
    init(sourcePath: String) throws {
        self.sourcePath = sourcePath
        let url = URL(fileURLWithPath: sourcePath)
        
        let fd = open(url.path, O_RDONLY)
        if fd == -1 {
            fatalError()
        }
        if flock(fd, LOCK_EX) != 0 {
            fatalError()
        }
        defer {
            flock(fd, LOCK_UN)
            close(fd)
        }
        
        let handle = FileHandle(fileDescriptor: fd, closeOnDealloc: false)
        let data = handle.readDataToEndOfFile()
        guard let src = String(data: data, encoding: .utf8) else {
            fatalError()
        }
        self.sourceText = src
        self.syntaxTree = try Parser.parse(source: sourceText)
        self.store = ResultStore()
        self.location = LocationHandler(file: sourcePath, source: sourceText)
    }
    
    func performExtraction() {
        let visitor = Visitor(store: store, location: location)
        visitor.walk(syntaxTree)
    }
}
