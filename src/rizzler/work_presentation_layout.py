"""V26 native-editable presentation compositor with genuine layout variation.

The LLM's independently qualified slide kind and optional approved chart
plan select the composition. No static topic keyword heuristics or invented
data. Text, charts, source notes and shapes remain editable PowerPoint
objects; the strict renderer/pixel reviewer validates final appearance.
"""
from __future__ import annotations

from pathlib import Path

KINDS=frozenset({
    "takeaway","comparison","process","evidence","metrics","decision"})


def render_professional_storyboard(path: Path,blueprint: dict, *,
                                   title: str,sources: tuple[str,...],
                                   table=None) -> None:
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_AUTO_SIZE,PP_ALIGN
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE

    slides=blueprint["slides"]
    if not isinstance(slides,list) or not 1<=len(slides)<=36:
        raise ValueError("Unbounded presentation material")
    palette={
        "ink":RGBColor(22,38,58),
        "muted":RGBColor(96,112,128),
        "teal":RGBColor(7,115,112),
        "ice":RGBColor(241,247,248),
        "line":RGBColor(213,227,232),
        "orange":RGBColor(206,107,55),
        "white":RGBColor(255,255,255),
        "soft":RGBColor(247,249,251),
    }
    p=Presentation()
    p.slide_width=Inches(13.333)
    p.slide_height=Inches(7.5)

    def rect(slide,x,y,w,h,*,color=None,line=None,radius=False):
        sh=slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
            Inches(x),Inches(y),Inches(w),Inches(h))
        if color is None:
            sh.fill.background()
        else:
            sh.fill.solid()
            sh.fill.fore_color.rgb=color
        if line is None:
            sh.line.fill.background()
        else:
            sh.line.color.rgb=line
        return sh

    def words(slide,content,x,y,w,h,*,font=17,bold=False,ink="ink",
              alignment=None,margin=.05):
        if not isinstance(content,str) or not content:
            return None
        sh=slide.shapes.add_textbox(
            Inches(x),Inches(y),Inches(w),Inches(h))
        frame=sh.text_frame
        frame.clear()
        frame.word_wrap=True
        frame.auto_size=MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        frame.margin_left=Inches(margin)
        frame.margin_right=Inches(margin)
        frame.margin_top=Inches(.04)
        frame.margin_bottom=Inches(.03)
        for index,line in enumerate(content.split("\n")):
            item=frame.paragraphs[0] if index==0 else frame.add_paragraph()
            item.text=line
            item.font.name="Aptos"
            item.font.size=Pt(font)
            item.font.bold=bold
            item.font.color.rgb=palette[ink]
            if alignment is not None:
                item.alignment=alignment
        return sh

    def body_cards(slide,bullets,*,x=.85,y=2.82,width=11.55,
                   height=3.72,columns=2,style="soft"):
        n=len(bullets)
        columns=min(columns,n)
        rows=(n+columns-1)//columns
        gap=.18
        cell_width=(width-gap*(columns-1))/columns
        cell_height=(height-gap*(rows-1))/rows
        for idx,text in enumerate(bullets):
            cx=x+(idx%columns)*(cell_width+gap)
            cy=y+(idx//columns)*(cell_height+gap)
            rect(slide,cx,cy,cell_width,cell_height,
                 color=palette[style],radius=True)
            rect(slide,cx+.12,cy+.17,.045,max(.15,cell_height-.36),
                 color=palette["teal"])
            words(slide,text,cx+.32,cy+.16,cell_width-.54,
                  max(.27,cell_height-.3),
                  font=17 if columns<=2 else 14)

    def add_chart(slide,item,*,x=6.1,y=2.75,w=6.2,h=3.6):
        if table is None:
            raise ValueError("Data-bound chart has no original table")
        from .work_visual_strategy import chart_values
        categories,measure=chart_values(item,table)
        if not categories:
            raise ValueError("Chart is empty")
        chart_data=CategoryChartData()
        chart_data.categories=categories
        for label,data in measure.items():
            chart_data.add_series(label[:80],data)
        chart_type=(XL_CHART_TYPE.LINE_MARKERS
                    if item["visual_type"]=="line"
                    else XL_CHART_TYPE.COLUMN_CLUSTERED)
        ch=slide.shapes.add_chart(
            chart_type,Inches(x),Inches(y),
            Inches(w),Inches(h),chart_data).chart
        ch.has_legend=len(measure)>1
        ch.value_axis.has_major_gridlines=True
        ch.chart_style=10
        return ch

    def layout(slide,plan,index):
        bullets=plan["bullets"]
        kind=plan["kind"]
        if kind not in KINDS or not 2<=len(bullets)<=6:
            raise ValueError("Unapproved slide content or kind")
        visual=blueprint.get("visual_plan")
        choice=visual["slides"][index] if visual else None
        has_chart=choice is not None and choice["visual_type"]!="none"

        if has_chart:
            # The chart should visually support the main metric claim.
            rect(slide,5.92,2.66,6.54,3.96,color=palette["soft"],radius=True)
            add_chart(slide,choice)
            body_cards(slide,bullets,x=.79,y=2.76,width=4.85,
                       height=3.74,columns=1)
        elif kind=="takeaway":
            # One clear executive conclusion, supporting factors underneath.
            rect(slide,.79,2.72,11.8,.09,color=palette["teal"])
            body_cards(slide,bullets,x=.80,y=3.02,
                       width=11.72,height=3.45,columns=2)
        elif kind=="comparison":
            # Evidence grouped side-by-side for readable contrasts.
            columns=2 if len(bullets)<=4 else 3
            body_cards(slide,bullets,x=.80,y=2.80,
                       width=11.72,height=3.86,columns=columns)
        elif kind=="process":
            # Connected progression; each step remains an editable shape.
            if len(bullets)<=4:
                cell=(11.78-.22*(len(bullets)-1))/len(bullets)
                for i,text in enumerate(bullets):
                    x=.79+i*(cell+.22)
                    rect(slide,x,3.08,cell,2.76,
                         color=palette["ice"],radius=True)
                    rect(slide,x+.19,3.30,.49,.49,
                         color=palette["teal"],radius=True)
                    words(slide,str(i+1),x+.26,3.36,.35,.32,
                          font=14,bold=True,ink="white")
                    words(slide,text,x+.20,4.02,
                          cell-.40,1.52,font=16)
                    if i<len(bullets)-1:
                        rect(slide,x+cell+.01,4.45,.19,.035,
                             color=palette["orange"])
            else:
                body_cards(slide,bullets,x=.80,y=2.85,
                           width=11.72,height=3.65,columns=3)
        elif kind=="decision":
            rect(slide,.79,2.76,3.1,3.72,
                 color=palette["ink"],radius=True)
            words(slide,"DECISION\nAND IMPLICATIONS",
                  1.05,3.10,2.5,2.8,font=22,bold=True,ink="white")
            body_cards(slide,bullets,x=4.11,y=2.76,
                       width=8.32,height=3.73,columns=2)
        elif kind=="evidence":
            # Source-backed audit findings should remain legible, not decorative.
            body_cards(slide,bullets,x=.80,y=2.77,
                       width=11.72,height=3.78,
                       columns=2 if len(bullets)<=4 else 3)
        elif kind=="metrics":
            body_cards(slide,bullets,x=.80,y=2.78,
                       width=11.72,height=3.78,columns=2)

    for index,plan in enumerate(slides):
        slide=p.slides.add_slide(p.slide_layouts[6])
        bg=slide.background.fill
        bg.solid()
        bg.fore_color.rgb=palette["white"]
        rect(slide,0,0,.16,7.5,color=palette["teal"])
        words(slide,"RIZZLER  /  "+plan["kind"].upper(),
              .79,.39,9.8,.37,font=11,bold=True,ink="teal")
        words(slide,f"{index+1:02d} / {len(slides):02d}",
              11.35,.39,1.1,.38,font=12,bold=True,ink="muted",
              alignment=PP_ALIGN.RIGHT)
        words(slide,plan["title"],.79,.91,11.68,.79,
              font=29,bold=True)
        words(slide,plan["message"],.79,1.78,11.72,.83,
              font=18,bold=True,ink="teal")
        rect(slide,.79,6.85,11.74,.018,color=palette["line"])
        if plan["source_urls"]:
            domains=[]
            for url in plan["source_urls"]:
                try:
                    from urllib.parse import urlsplit
                    host=urlsplit(url).netloc
                except (ValueError,TypeError):
                    host=""
                if host and host not in domains:
                    domains.append(host)
            words(slide,"Sources: "+", ".join(domains),
                  .79,6.99,10.55,.30,font=9,ink="muted")
        words(slide,"RIZZLER • VERIFIED WORK",
              10.58,7.08,1.88,.22,font=8,
              ink="muted",alignment=PP_ALIGN.RIGHT)
        layout(slide,plan,index)
        notes=slide.notes_slide.notes_text_frame
        notes.text=(
            "SOURCE REFERENCES (not automatic factual proof):\n"+
            "\n".join(plan["source_urls"])+
            "\nSOURCE SECTION IDS: "+
            ",".join(map(str,plan["section_ids"])))
    p.core_properties.title=title
    p.core_properties.author="Rizzler Work Agent"
    path.parent.mkdir(parents=True,exist_ok=True)
    p.save(path)
