// manual_maker のデザイン定義（色・フォント・レイアウトを変えたいときはここを編集）

#let accent = rgb("#d92d20")
#let muted = luma(110)
#let max-shot-height = 13cm

// 文書全体の設定: #show: manual.with(title: "...", author: "...")
#let manual(title: "", author: "", body) = {
  set document(title: title, author: author)
  set page(
    paper: "a4",
    margin: (x: 20mm, top: 20mm, bottom: 22mm),
    numbering: "1",
    footer: context {
      if counter(page).get().first() > 1 {
        set text(9pt, fill: muted)
        title
        h(1fr)
        counter(page).display("1")
      }
    },
  )
  set text(font: ("BIZ UDPGothic", "Noto Sans JP", "Yu Gothic"), size: 10.5pt, lang: "ja")
  set par(justify: true, leading: 0.8em)
  show heading.where(level: 1): it => {
    set text(17pt)
    block(below: 1em, it.body)
    line(length: 100%, stroke: 0.6pt + luma(180))
    v(0.6em)
  }
  show heading.where(level: 2): set text(13pt)
  show heading.where(level: 2): set block(above: 1.6em, below: 0.8em)
  body
}

// 表紙
#let cover(title: "", app: "", created: "", author: "") = page(numbering: none, footer: none, {
  v(1fr)
  if app != "" {
    text(12pt, fill: muted, app)
    v(0.4em)
  }
  text(28pt, weight: "bold", title)
  v(0.6em)
  line(length: 100%, stroke: 2pt + accent)
  v(1fr)
  set text(11pt, fill: muted)
  grid(columns: (auto, 1fr), column-gutter: 1em, row-gutter: 0.6em,
    [作成日], created,
    ..if author != "" { ([作成者], author) } else { () },
  )
})

// 章見出し（章ごとに改ページ）
#let section(title) = {
  pagebreak(weak: true)
  heading(level: 1, title)
}

// スクリーンショット + クリック位置の強調
// img: image("...") / click: (x: 0-1, y: 0-1) または none
#let shot(img, click: none, num: none) = layout(size => {
  let natural = measure(img)
  let ratio = natural.width / natural.height
  let w = calc.min(size.width, max-shot-height * ratio)
  let h = w / ratio
  align(center, block(width: w, height: h, stroke: 0.5pt + luma(200), {
    set image(width: w)
    img
    if click != none {
      let r = 11pt
      place(top + left, dx: click.x * w - r, dy: click.y * h - r,
        circle(radius: r, stroke: 2.5pt + accent, fill: accent.transparentize(85%)))
      if num != none {
        place(top + left, dx: click.x * w + r * 0.55, dy: click.y * h - r * 2.1,
          box(fill: accent, radius: 50%, width: 14pt, height: 14pt,
            align(center + horizon, text(8pt, fill: white, weight: "bold", str(num)))))
      }
    }
  }))
})

#let note-box(body) = block(
  width: 100%, inset: (x: 10pt, y: 8pt), radius: 3pt,
  fill: rgb("#fff8e6"), stroke: (left: 3pt + rgb("#f0b429")),
  [#text(weight: "bold")[補足] #h(0.5em) #body],
)

#let _empty(x) = x == none or x == [] or x == ""

// 1手順分: 見出し + 画像 + 説明 + 補足
#let step(num, title, img, click: none, note: none, body) = {
  block(width: 100%, breakable: false, {
    heading(level: 2)[#text(fill: accent)[手順 #num.] #title]
    shot(img, click: click, num: num)
  })
  if not _empty(body) {
    v(0.4em)
    body
  }
  if not _empty(note) {
    v(0.2em)
    note-box(note)
  }
}
