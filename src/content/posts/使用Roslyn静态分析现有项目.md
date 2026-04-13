---
title: 使用Roslyn静态分析现有项目
published: 2021-03-18
description: "使用 Visual Studio 提供的 Syntax Visualizer，我们可以实时看到一个代码文件中的语法树。这对我们基于 Roslyn 编写静态分析和"
tags: []
category: 编程语言
draft: false
---

使用 Visual Studio 提供的 Syntax Visualizer，我们可以实时看到一个代码文件中的语法树。这对我们基于 Roslyn 编写静态分析和修改工具非常有帮助。



## 工具安装

在安装 Visual Studio 时，选择了 Visual Studio 扩展开发的工作负载，勾选了 .NET Compiler Platform SDK，即可。



## Syntax Visual

语法可视化树中有三种不同颜色的节点：

- 蓝色：[SyntaxNode](https://docs.microsoft.com/zh-cn/dotnet/api/microsoft.codeanalysis.syntaxnode?view=roslyn-dotnet)，表示声明、语句、子句和表达式等语法构造。
- 绿色：[SyntaxToken](https://docs.microsoft.com/zh-cn/dotnet/api/microsoft.codeanalysis.syntaxtoken?view=roslyn-dotnet)，表示关键字、标识符、运算符等标点。
- 红色：[SyntaxTrivia](https://docs.microsoft.com/zh-cn/dotnet/api/microsoft.codeanalysis.syntaxtrivia?view=roslyn-dotnet)，代表语法上不重要的信息，例如标记、预处理指令和注释之间的空格。



### 用起来

![image-20230907163724401](/images/posts/使用Roslyn静态分析现有项目/image-20230907163724401.png)

```csharp
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using Microsoft.Build.Locator;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Symbols;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.MSBuild;
using Microsoft.CodeAnalysis.Text;

namespace TestMyRewriter
{
    class Program
    {
        static async Task Main(string[] args)
        {   //原始代码
            string strCode = @"
                  public class Foo
                  {
                      public string _bar = ""baz"";  
                      public string strHello = ""heloo world"";
                  }";
            var tree = CSharpSyntaxTree.ParseText(strCode);
            var Mscorlib = MetadataReference.CreateFromFile(typeof(object).Assembly.Location);
            var compilation = CSharpCompilation.Create("MyCompilation",
                syntaxTrees: new[] { tree }, references: new[] { Mscorlib });
            // 获得语义模型
            var model = compilation.GetSemanticModel(tree);
            var root = model.SyntaxTree.GetRoot();
            // 用Visit重写代码
            var rw = new LiteralRewriter();
            var newRoot = rw.Visit(root);
            // 新生成代码
            string strNewCode = newRoot.GetText().ToString();
            Console.WriteLine(strNewCode);
            Console.ReadLine();
        }
    }

    class LiteralRewriter : CSharpSyntaxRewriter      // 继承CSharpSyntaxRewriter
    {
        public override SyntaxNode VisitLiteralExpression(LiteralExpressionSyntax node) // 重载 VisitLiteralExpression 方法, 输入节点是 文字表达式
        {
            if (!node.IsKind(SyntaxKind.StringLiteralExpression))
            { return base.VisitLiteralExpression(node); }
            // 重新构造一个字符串表达式
            var retVal = SyntaxFactory.LiteralExpression(SyntaxKind.StringLiteralExpression,
                                                         SyntaxFactory.Literal("NotBaz"));
            return retVal;
        }
    }
}
```



![image-20230907163810748](/images/posts/使用Roslyn静态分析现有项目/image-20230907163810748.png)



## 加载一个项目

```csharp
static async Task Main(string[] args)
{
    string solutionPath = @"H:\CSharpProject\MyConsole\MyConsole.sln";

    if (!MSBuildLocator.IsRegistered) MSBuildLocator.RegisterDefaults();
    using (var w = MSBuildWorkspace.Create())
    {
        var solution = await w.OpenSolutionAsync(solutionPath);
        //await SolutionAttributeUpdater.UpdateAttributes(solution);
    }
}
```



官网案例：https://github.com/dotnet/samples/tree/main/csharp/roslyn-sdk



### 重构代码

- 创建CodeAnalysis 工程，加载要分析的工程项目
- 设定要分析的脚本，也可以遍历全部或自定义筛选
- 通过脚本可以获取抽象语法树（另外直接用字符串源码也可以生成抽象语法树）
- 实现语法重写（Syntax Rewriter）
- 将新的语法树结果写入脚本，即可完成自定义重构



```csharp
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using Microsoft.Build.Locator;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Symbols;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.MSBuild;
using Microsoft.CodeAnalysis.Text;

namespace TestMyRewriter
{
    class Program
    {
        static async Task Main(string[] args)
        {
            string solutionPath = @"H:\CSharpProject\MyConsole\MyConsole.sln";

            if (!MSBuildLocator.IsRegistered) MSBuildLocator.RegisterDefaults();
            using (var w = MSBuildWorkspace.Create())
            {
                var solution = await w.OpenSolutionAsync(solutionPath);
                //await SolutionAttributeUpdater.UpdateAttributes(solution);
                var project = solution.Projects.First(x => x.Name == "MyConsole");

                var document = project.Documents.First(x =>
                        x.Name.Equals("Program.cs", StringComparison.InvariantCultureIgnoreCase));

                var tree = await document.GetSyntaxTreeAsync();
                var syntax = tree.GetCompilationUnitRoot();

                var visitor = new TypeParameterVisitor();
                var node = visitor.Visit(syntax);

                var text = node.GetText();
                File.WriteAllText(document.FilePath, text.ToString());
            }
        }
    }

    public class SolutionAttributeUpdater
    {
        public static async Task<Solution> UpdateAttributes(Solution solution)
        {
            foreach (var project in solution.Projects)
            {
                foreach (var document in project.Documents)
                {
                    var syntaxTree = await document.GetSyntaxTreeAsync();
                    var root = syntaxTree.GetRoot();

                    var descentants = root.DescendantNodes().Where(curr => curr is AttributeListSyntax).ToList();
                    if (descentants.Any())
                    {
                        var attributeList = SyntaxFactory.AttributeList(
                            SyntaxFactory.SingletonSeparatedList(
                                SyntaxFactory.Attribute(SyntaxFactory.IdentifierName("CookiesAttribute"), SyntaxFactory.AttributeArgumentList(SyntaxFactory.SeparatedList(new[] { SyntaxFactory.AttributeArgument(
                                    SyntaxFactory.LiteralExpression(
                                                                SyntaxKind.StringLiteralExpression, SyntaxFactory.Literal(@"SampleClass"))
                                    )})))));

                        root = root.ReplaceNodes(descentants, (node, n2) => attributeList);
                        solution = solution.WithDocumentSyntaxRoot(document.Id, root);
                    }
                }
            }
            return solution;
        }
    }

    class TypeParameterVisitor : CSharpSyntaxRewriter
    {
        public override SyntaxNode VisitTypeParameterList(TypeParameterListSyntax node)
        {
            var parameters = new SeparatedSyntaxList<TypeParameterSyntax>();
            parameters = parameters.Add(SyntaxFactory.TypeParameter("TParameter"));

         
            var lessThanToken = this.VisitToken(node.LessThanToken);
            var greaterThanToken = this.VisitToken(node.GreaterThanToken);
            return node.Update(lessThanToken, parameters, greaterThanToken);
        }
    }


}
```

